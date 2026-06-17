from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.clock.db_sync import ClockDbSyncService
from app.clock.sync import SyncCursorState, SyncRunResult
from app.domain.enums import AutomationPhase, ControlMode
from app.domain.models import PropertyRegistry, Room, RoomRegistry
from app.persistence import models as db
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
    apply_sync(engine, registry, policy, [move_back_to_214], LATER)

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


def utc_readback(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
