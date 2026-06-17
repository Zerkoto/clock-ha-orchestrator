from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.clock.db_sync import ClockDbSyncService
from app.clock.sync import SyncCursorState, SyncRunResult
from app.domain.enums import AutomationPhase, BookingStatus, ControlMode, ManualHvacMode
from app.domain.models import PropertyRegistry, Room, RoomRegistry
from app.persistence import models as db
from app.policy.control import RoomControlCommandService
from tests.conftest import booking

NOW = datetime(2026, 12, 20, 10, 0, tzinfo=UTC)
LATER = datetime(2026, 12, 20, 10, 5, tzinfo=UTC)
CORRELATION_ID = UUID("00000000-0000-0000-0000-000000000123")


@pytest.fixture
def engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db.Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def registry() -> RoomRegistry:
    return RoomRegistry(
        property=PropertyRegistry(key="local_stay_razlog", name="Local Stay Hotel & Suites"),
        rooms=[
            Room(key="214", name="Apartment 214", floor="2", clock_room_id="clock-room-214"),
            Room(key="215", name="Apartment 215", floor="2", clock_room_id="clock-room-215"),
        ],
    )


def test_db_sync_upserts_booking_assignment_state_and_outbox(
    engine: Engine,
    registry: RoomRegistry,
    policy,
) -> None:
    result = apply_sync(engine, registry, policy, [booking()], NOW)

    assert result.success is True
    assert result.processed_bookings == 1
    assert result.affected_room_keys == ("214",)
    assert result.room_states_created == 1
    assert result.outbox_events_created == 2

    with Session(engine) as session:
        assert count_rows(session, db.Booking) == 1
        assert count_rows(session, db.BookingRoomAssignment) == 1
        assert count_rows(session, db.RoomState) == 1
        assert count_rows(session, db.OutboxEvent) == 2
        cursor = session.execute(select(db.SyncCursor)).scalar_one()
        assert utc_readback(cursor.last_success_at) == NOW

        topics = {event.topic for event in session.execute(select(db.OutboxEvent)).scalars()}
        assert topics == {
            "hotel/v1/rooms/214/pms/state",
            "hotel/v1/rooms/214/intent/state",
        }
        payloads = [event.payload for event in session.execute(select(db.OutboxEvent)).scalars()]
        intent_payload = next(payload for payload in payloads if "intent_version" in payload)
        assert intent_payload["intent_version"] == 1
        encoded = json.dumps(payloads, sort_keys=True)
        assert "guest" not in encoded.lower()
        assert "email" not in encoded.lower()
        assert "card" not in encoded.lower()


def test_reprocessing_identical_input_creates_no_semantic_outbox_event(
    engine: Engine,
    registry: RoomRegistry,
    policy,
) -> None:
    apply_sync(engine, registry, policy, [booking()], NOW)
    result = apply_sync(engine, registry, policy, [booking()], LATER)

    assert result.room_states_created == 0
    assert result.outbox_events_created == 0

    with Session(engine) as session:
        assert count_rows(session, db.RoomState) == 1
        assert count_rows(session, db.OutboxEvent) == 2


def test_room_moves_recalculate_old_and_new_rooms_and_keep_assignment_history(
    engine: Engine,
    registry: RoomRegistry,
    policy,
) -> None:
    apply_sync(engine, registry, policy, [booking()], NOW)
    move_to_215 = booking(room_id="clock-room-215", room_number="215")
    result = apply_sync(engine, registry, policy, [move_to_215], LATER)
    move_back_to_214 = booking()
    apply_sync(engine, registry, policy, [move_back_to_214], LATER + timedelta(minutes=1))

    assert result.affected_room_keys == ("214", "215")
    assert result.room_states_created == 2
    assert result.outbox_events_created == 4

    with Session(engine) as session:
        assignments = list(session.execute(select(db.BookingRoomAssignment)).scalars())
        assert len(assignments) == 3
        current = [assignment for assignment in assignments if assignment.is_current]
        assert len(current) == 1
        assert current[0].physical_room_number == "214"
        assert count_rows(session, db.RoomState) == 5
        assert count_rows(session, db.OutboxEvent) == 10
        intent_versions = [
            event.payload["intent_version"]
            for event in session.execute(
                select(db.OutboxEvent)
                .where(db.OutboxEvent.topic == "hotel/v1/rooms/214/intent/state")
                .order_by(db.OutboxEvent.created_at, db.OutboxEvent.id)
            ).scalars()
        ]
        assert intent_versions == [1, 2, 3]


def test_policy_tick_moves_reserved_room_to_pre_arrival_without_clock_delta(
    engine: Engine,
    registry: RoomRegistry,
    policy,
) -> None:
    future = booking(arrival=date(2026, 12, 21), departure=date(2026, 12, 24))
    apply_sync(engine, registry, policy, [future], NOW)

    policy_tick_at = datetime(2026, 12, 21, 10, 30, tzinfo=UTC)
    with Session(engine) as session:
        service = ClockDbSyncService(session=session, room_registry=registry, policy=policy)
        result = service.evaluate_all_rooms(now=policy_tick_at, correlation_id=CORRELATION_ID)

    assert result.affected_room_keys == ("214", "215")
    assert result.room_states_created == 2
    assert result.outbox_events_created == 4

    with Session(engine) as session:
        room_214_id = session.execute(select(db.Room.id).where(db.Room.key == "214")).scalar_one()
        states = list(
            session.execute(
                select(db.RoomState)
                .where(db.RoomState.room_id == room_214_id)
                .order_by(db.RoomState.created_at, db.RoomState.id)
            ).scalars()
        )
        assert [state.automation_phase for state in states] == [
            AutomationPhase.RESERVED.value,
            AutomationPhase.PRE_ARRIVAL.value,
        ]
        assert [state.intent_version for state in states] == [1, 2]


def test_assignment_removal_recalculates_old_room_without_unassigned_intent(
    engine: Engine,
    registry: RoomRegistry,
    policy,
) -> None:
    apply_sync(engine, registry, policy, [booking()], NOW)
    unassigned = booking(room_id=None, room_number=None)
    result = apply_sync(engine, registry, policy, [unassigned], LATER)

    assert result.affected_room_keys == ("214",)
    assert result.room_states_created == 1
    assert result.outbox_events_created == 2
    assert result.audit_events_created >= 2

    with Session(engine) as session:
        current_assignments = session.execute(
            select(db.BookingRoomAssignment).where(db.BookingRoomAssignment.is_current.is_(True))
        ).scalars()
        assert list(current_assignments) == []
        topics = [event.topic for event in session.execute(select(db.OutboxEvent)).scalars()]
        assert all("/rooms/214/" in topic for topic in topics)
        assert all("/rooms/None/" not in topic for topic in topics)


def test_overlapping_active_bookings_create_conflict_intent(
    engine: Engine,
    registry: RoomRegistry,
    policy,
) -> None:
    conflict = booking(clock_booking_id="booking-2")
    result = apply_sync(engine, registry, policy, [booking(), conflict], NOW)

    assert result.affected_room_keys == ("214",)
    assert result.room_states_created == 1
    assert result.outbox_events_created == 2

    with Session(engine) as session:
        room_state = session.execute(select(db.RoomState)).scalar_one()
        assert room_state.automation_phase == AutomationPhase.CONFLICT.value
        intent = session.execute(
            select(db.OutboxEvent).where(db.OutboxEvent.topic == "hotel/v1/rooms/214/intent/state")
        ).scalar_one()
        assert intent.payload["automation_phase"] == AutomationPhase.CONFLICT.value
        assert intent.payload["control_mode"] == ControlMode.OFF.value
        assert intent.payload["hvac"]["enabled"] is False


def test_policy_tick_loads_active_manual_override(
    engine: Engine,
    registry: RoomRegistry,
    policy,
) -> None:
    apply_sync(engine, registry, policy, [booking()], NOW)
    with Session(engine) as session, session.begin():
        room_id = session.execute(select(db.Room.id).where(db.Room.key == "214")).scalar_one()
        session.add(
            db.RoomPolicyOverride(
                room_id=room_id,
                command_id=UUID("00000000-0000-0000-0000-000000000333"),
                control_mode=ControlMode.MANUAL.value,
                hvac_mode=ManualHvacMode.COOL.value,
                target_temperature_c=20,
                water_heater_enabled=False,
                starts_at=NOW,
                expires_at=NOW + timedelta(hours=1),
                until_checkout=False,
                created_by="test",
            )
        )

    with Session(engine) as session:
        service = ClockDbSyncService(session=session, room_registry=registry, policy=policy)
        result = service.evaluate_all_rooms(
            now=NOW + timedelta(minutes=1),
            correlation_id=CORRELATION_ID,
        )

    assert "214" in result.affected_room_keys

    with Session(engine) as session:
        latest_intent = session.execute(
            select(db.OutboxEvent)
            .where(db.OutboxEvent.topic == "hotel/v1/rooms/214/intent/state")
            .order_by(db.OutboxEvent.created_at.desc(), db.OutboxEvent.id.desc())
            .limit(1)
        ).scalar_one()
        assert latest_intent.payload["automation_phase"] == AutomationPhase.MANUAL_OVERRIDE.value
        assert latest_intent.payload["control_mode"] == ControlMode.MANUAL.value
        assert latest_intent.payload["hvac"]["mode"] == ManualHvacMode.COOL.value


def test_home_assistant_temperature_command_creates_override_state_and_intent(
    engine: Engine,
    registry: RoomRegistry,
    policy,
) -> None:
    apply_sync(engine, registry, policy, [booking()], NOW)
    with Session(engine) as session, session.begin():
        result = RoomControlCommandService(
            session=session,
            room_registry=registry,
            policy=policy,
        ).apply_mqtt_command(
            room_key="214",
            field="temperature",
            payload=b"21.5",
            now=LATER,
            correlation_id=CORRELATION_ID,
        )

    assert result.accepted is True

    with Session(engine) as session:
        ClockDbSyncService(
            session=session, room_registry=registry, policy=policy
        ).evaluate_room_keys(
            room_keys={"214"},
            now=LATER,
            correlation_id=CORRELATION_ID,
        )

    with Session(engine) as session:
        control_state = session.execute(
            select(db.OutboxEvent)
            .where(db.OutboxEvent.topic == "hotel/v1/rooms/214/control/state")
            .order_by(db.OutboxEvent.created_at.desc(), db.OutboxEvent.id.desc())
            .limit(1)
        ).scalar_one()
        assert control_state.payload["control_mode"] == ControlMode.MANUAL.value
        assert control_state.payload["manual_target_temperature_c"] == 21.5

        latest_intent = session.execute(
            select(db.OutboxEvent)
            .where(db.OutboxEvent.topic == "hotel/v1/rooms/214/intent/state")
            .order_by(db.OutboxEvent.created_at.desc(), db.OutboxEvent.id.desc())
            .limit(1)
        ).scalar_one()
        assert latest_intent.payload["automation_phase"] == AutomationPhase.MANUAL_OVERRIDE.value
        assert latest_intent.payload["hvac"]["target_temperature_c"] == 21.5


def test_return_to_automatic_suppresses_older_manual_override(
    engine: Engine,
    registry: RoomRegistry,
    policy,
) -> None:
    apply_sync(engine, registry, policy, [booking()], NOW)
    with Session(engine) as session, session.begin():
        service = RoomControlCommandService(
            session=session,
            room_registry=registry,
            policy=policy,
        )
        service.apply_mqtt_command(
            room_key="214",
            field="temperature",
            payload=b"21.5",
            now=NOW,
            correlation_id=UUID("00000000-0000-0000-0000-000000000444"),
        )
        service.apply_mqtt_command(
            room_key="214",
            field="return-to-automatic",
            payload=b"return",
            now=LATER,
            correlation_id=UUID("00000000-0000-0000-0000-000000000445"),
        )

    with Session(engine) as session:
        ClockDbSyncService(
            session=session, room_registry=registry, policy=policy
        ).evaluate_room_keys(
            room_keys={"214"},
            now=LATER,
            correlation_id=CORRELATION_ID,
        )

    with Session(engine) as session:
        latest_intent = session.execute(
            select(db.OutboxEvent)
            .where(db.OutboxEvent.topic == "hotel/v1/rooms/214/intent/state")
            .order_by(db.OutboxEvent.created_at.desc(), db.OutboxEvent.id.desc())
            .limit(1)
        ).scalar_one()
        assert latest_intent.payload["automation_phase"] == AutomationPhase.PRE_ARRIVAL.value
        assert latest_intent.payload["control_mode"] == ControlMode.AUTOMATIC.value


def test_timed_manual_override_expires_and_publishes_automatic_control_state(
    engine: Engine,
    registry: RoomRegistry,
    policy,
) -> None:
    checked_in = booking(status=BookingStatus.CHECKED_IN)
    apply_sync(engine, registry, policy, [checked_in], NOW)
    with Session(engine) as session, session.begin():
        RoomControlCommandService(
            session=session,
            room_registry=registry,
            policy=policy,
        ).apply_mqtt_command(
            room_key="214",
            field="temperature",
            payload=b"21.5",
            now=LATER,
            correlation_id=UUID("00000000-0000-0000-0000-000000000446"),
        )
    with Session(engine) as session:
        ClockDbSyncService(
            session=session,
            room_registry=registry,
            policy=policy,
        ).evaluate_room_keys(
            room_keys={"214"},
            now=LATER,
            correlation_id=UUID("00000000-0000-0000-0000-000000000447"),
        )

    expired_at = LATER + timedelta(minutes=61)
    with Session(engine) as session:
        result = ClockDbSyncService(
            session=session,
            room_registry=registry,
            policy=policy,
        ).evaluate_room_keys(
            room_keys={"214"},
            now=expired_at,
            correlation_id=CORRELATION_ID,
        )

    assert result.audit_events_created >= 1

    with Session(engine) as session:
        latest_control_state = latest_outbox_payload(
            session,
            "hotel/v1/rooms/214/control/state",
        )
        latest_intent = latest_outbox_payload(session, "hotel/v1/rooms/214/intent/state")
        latest_override = session.execute(
            select(db.RoomPolicyOverride)
            .where(db.RoomPolicyOverride.room_id == select_room_id(session, "214"))
            .order_by(db.RoomPolicyOverride.starts_at.desc(), db.RoomPolicyOverride.id.desc())
            .limit(1)
        ).scalar_one()

    assert latest_control_state["control_mode"] == ControlMode.AUTOMATIC.value
    assert latest_control_state["active"] is False
    assert latest_control_state["command_id"] is None
    assert latest_intent["automation_phase"] == AutomationPhase.OCCUPIED.value
    assert latest_override.control_mode == ControlMode.AUTOMATIC.value


def test_until_checkout_override_ends_at_checkout_and_clears_control_state(
    engine: Engine,
    registry: RoomRegistry,
    policy,
) -> None:
    checked_in = booking(status=BookingStatus.CHECKED_IN)
    apply_sync(engine, registry, policy, [checked_in], NOW)
    with Session(engine) as session, session.begin():
        service = RoomControlCommandService(
            session=session,
            room_registry=registry,
            policy=policy,
        )
        service.apply_mqtt_command(
            room_key="214",
            field="temperature",
            payload=b"21.5",
            now=LATER,
            correlation_id=UUID("00000000-0000-0000-0000-000000000448"),
        )
        result = service.apply_mqtt_command(
            room_key="214",
            field="duration",
            payload=b"until_checkout",
            now=LATER + timedelta(minutes=1),
            correlation_id=UUID("00000000-0000-0000-0000-000000000449"),
        )

    assert result.accepted is True

    with Session(engine) as session:
        ClockDbSyncService(
            session=session,
            room_registry=registry,
            policy=policy,
        ).evaluate_room_keys(
            room_keys={"214"},
            now=LATER + timedelta(minutes=2),
            correlation_id=UUID("00000000-0000-0000-0000-000000000450"),
        )

    after_checkout = datetime(2026, 12, 24, 9, 30, tzinfo=UTC)
    with Session(engine) as session:
        ClockDbSyncService(
            session=session,
            room_registry=registry,
            policy=policy,
        ).evaluate_room_keys(
            room_keys={"214"},
            now=after_checkout,
            correlation_id=CORRELATION_ID,
        )

    with Session(engine) as session:
        latest_control_state = latest_outbox_payload(
            session,
            "hotel/v1/rooms/214/control/state",
        )
        latest_intent = latest_outbox_payload(session, "hotel/v1/rooms/214/intent/state")

    assert latest_control_state["control_mode"] == ControlMode.AUTOMATIC.value
    assert latest_control_state["active"] is False
    assert latest_intent["automation_phase"] == AutomationPhase.CHECKOUT_DUE.value
    assert latest_intent["control_mode"] == ControlMode.AUTOMATIC.value


def test_until_checkout_override_does_not_carry_to_next_guest_same_room(
    engine: Engine,
    registry: RoomRegistry,
    policy,
) -> None:
    guest_a = booking(
        status=BookingStatus.CHECKED_IN,
        departure=date(2026, 12, 21),
        clock_booking_id="booking-a",
    ).model_copy(update={"payload_hash": "booking-a-in"})
    apply_sync(engine, registry, policy, [guest_a], NOW)
    with Session(engine) as session, session.begin():
        service = RoomControlCommandService(
            session=session,
            room_registry=registry,
            policy=policy,
        )
        service.apply_mqtt_command(
            room_key="214",
            field="temperature",
            payload=b"21.5",
            now=LATER,
            correlation_id=UUID("00000000-0000-0000-0000-000000000452"),
        )
        result = service.apply_mqtt_command(
            room_key="214",
            field="duration",
            payload=b"until_checkout",
            now=LATER + timedelta(minutes=1),
            correlation_id=UUID("00000000-0000-0000-0000-000000000453"),
        )

    assert result.accepted is True

    with Session(engine) as session:
        guest_a_row = session.execute(
            select(db.Booking).where(db.Booking.clock_booking_id == "booking-a")
        ).scalar_one()
        until_checkout_row = session.execute(
            select(db.RoomPolicyOverride)
            .where(db.RoomPolicyOverride.until_checkout.is_(True))
            .order_by(db.RoomPolicyOverride.starts_at.desc(), db.RoomPolicyOverride.id.desc())
            .limit(1)
        ).scalar_one()

    assert until_checkout_row.booking_id == guest_a_row.id
    assert utc_readback(until_checkout_row.checkout_at) == datetime(
        2026,
        12,
        21,
        9,
        0,
        tzinfo=UTC,
    )

    with Session(engine) as session:
        ClockDbSyncService(
            session=session,
            room_registry=registry,
            policy=policy,
        ).evaluate_room_keys(
            room_keys={"214"},
            now=LATER + timedelta(minutes=2),
            correlation_id=UUID("00000000-0000-0000-0000-000000000454"),
        )

    guest_a_checked_out = guest_a.model_copy(
        update={
            "booking_status": BookingStatus.CHECKED_OUT,
            "source_booking_status": BookingStatus.CHECKED_OUT.value,
            "payload_hash": "booking-a-out",
        }
    )
    guest_b_checked_in = booking(
        status=BookingStatus.CHECKED_IN,
        arrival=date(2026, 12, 21),
        departure=date(2026, 12, 24),
        clock_booking_id="booking-b",
    ).model_copy(update={"payload_hash": "booking-b-in"})
    before_guest_a_checkout_boundary = datetime(2026, 12, 21, 8, 30, tzinfo=UTC)

    apply_sync(
        engine,
        registry,
        policy,
        [guest_a_checked_out, guest_b_checked_in],
        before_guest_a_checkout_boundary,
    )

    with Session(engine) as session:
        latest_control_state = latest_outbox_payload(
            session,
            "hotel/v1/rooms/214/control/state",
        )
        latest_intent = latest_outbox_payload(session, "hotel/v1/rooms/214/intent/state")
        latest_pms_state = latest_outbox_payload(session, "hotel/v1/rooms/214/pms/state")
        latest_override = session.execute(
            select(db.RoomPolicyOverride)
            .where(db.RoomPolicyOverride.room_id == select_room_id(session, "214"))
            .order_by(db.RoomPolicyOverride.starts_at.desc(), db.RoomPolicyOverride.id.desc())
            .limit(1)
        ).scalar_one()

    assert latest_control_state["control_mode"] == ControlMode.AUTOMATIC.value
    assert latest_control_state["active"] is False
    assert latest_intent["automation_phase"] == AutomationPhase.OCCUPIED.value
    assert latest_intent["control_mode"] == ControlMode.AUTOMATIC.value
    assert latest_pms_state["clock_booking_id"] == "booking-b"
    assert latest_override.control_mode == ControlMode.AUTOMATIC.value


def test_until_checkout_command_requires_current_reservation(
    engine: Engine,
    registry: RoomRegistry,
    policy,
) -> None:
    with Session(engine) as session, session.begin():
        service = RoomControlCommandService(
            session=session,
            room_registry=registry,
            policy=policy,
        )
        service.apply_mqtt_command(
            room_key="214",
            field="temperature",
            payload=b"21.5",
            now=NOW,
            correlation_id=UUID("00000000-0000-0000-0000-000000000451"),
        )
        result = service.apply_mqtt_command(
            room_key="214",
            field="duration",
            payload=b"until_checkout",
            now=LATER,
            correlation_id=CORRELATION_ID,
        )

    assert result.accepted is False
    assert result.error == "until_checkout requires a current assigned reservation"


def test_invalid_home_assistant_command_is_audited_without_outbox(
    engine: Engine,
    registry: RoomRegistry,
    policy,
) -> None:
    apply_sync(engine, registry, policy, [booking()], NOW)
    with Session(engine) as session, session.begin():
        before = count_rows(session, db.OutboxEvent)
        result = RoomControlCommandService(
            session=session,
            room_registry=registry,
            policy=policy,
        ).apply_mqtt_command(
            room_key="214",
            field="duration",
            payload=b"15",
            now=LATER,
            correlation_id=CORRELATION_ID,
        )

        assert result.accepted is False
        assert count_rows(session, db.OutboxEvent) == before
        audit = session.execute(
            select(db.AuditEvent)
            .where(db.AuditEvent.event_type == "manual_override_command_rejected")
            .limit(1)
        ).scalar_one()
        assert audit.payload["field"] == "duration"


def test_failed_sync_run_does_not_advance_cursor(
    engine: Engine,
    registry: RoomRegistry,
    policy,
) -> None:
    apply_sync(engine, registry, policy, [booking()], NOW)
    failed = SyncRunResult(
        success=False,
        bookings=[],
        started_at=LATER,
        finished_at=LATER,
        next_cursor=SyncCursorState(last_success_at=NOW),
        error="ClockUnavailable",
    )

    with Session(engine) as session:
        service = ClockDbSyncService(session=session, room_registry=registry, policy=policy)
        result = service.apply_sync_result(failed, correlation_id=CORRELATION_ID)

    assert result.success is False

    with Session(engine) as session:
        cursor = session.execute(select(db.SyncCursor)).scalar_one()
        assert utc_readback(cursor.last_success_at) == NOW
        runs = list(session.execute(select(db.SyncRun).order_by(db.SyncRun.started_at)).scalars())
        assert [run.status for run in runs] == ["success", "failed"]


def test_sync_apply_rolls_back_when_booking_property_mismatches_registry(
    engine: Engine,
    registry: RoomRegistry,
    policy,
) -> None:
    bad_booking = booking().model_copy(update={"property_id": "other_property"})

    with pytest.raises(ValueError, match="property_id"):
        apply_sync(engine, registry, policy, [bad_booking], NOW)

    with Session(engine) as session:
        assert count_rows(session, db.Booking) == 0
        assert count_rows(session, db.SyncCursor) == 0
        assert count_rows(session, db.SyncRun) == 0
        assert count_rows(session, db.OutboxEvent) == 0


def apply_sync(
    engine: Engine,
    registry: RoomRegistry,
    policy,
    bookings,
    now: datetime,
):
    result = SyncRunResult(
        success=True,
        bookings=list(bookings),
        started_at=now,
        finished_at=now,
        next_cursor=SyncCursorState(last_success_at=now),
    )
    with Session(engine) as session:
        service = ClockDbSyncService(session=session, room_registry=registry, policy=policy)
        return service.apply_sync_result(result, correlation_id=CORRELATION_ID)


def count_rows(session: Session, model: type[db.Base]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def latest_outbox_payload(session: Session, topic: str) -> dict:
    return (
        session.execute(
            select(db.OutboxEvent)
            .where(db.OutboxEvent.topic == topic)
            .order_by(db.OutboxEvent.created_at.desc(), db.OutboxEvent.id.desc())
            .limit(1)
        )
        .scalar_one()
        .payload
    )


def select_room_id(session: Session, room_key: str) -> UUID:
    return session.execute(select(db.Room.id).where(db.Room.key == room_key)).scalar_one()


def utc_readback(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
