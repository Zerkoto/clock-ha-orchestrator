from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock.sync import SyncCursorState, SyncRunResult
from app.domain.enums import AttentionReason, BookingStatus
from app.domain.models import (
    DesiredRoomIntent,
    HotelPolicy,
    ManualOverride,
    NormalizedBooking,
    Room,
    RoomRegistry,
    RoomStateEvaluation,
)
from app.domain.state_machine import evaluate_room, evaluate_unassigned_booking
from app.mqtt.topics import MqttTopics
from app.persistence import models as db
from app.policy.control import latest_override_row, manual_override_from_row, override_row_is_active
from app.policy.engine import derive_room_intent

CLOCK_BOOKINGS_CURSOR_SOURCE = "clock_bookings"


@dataclass(frozen=True)
class PersistedSyncResult:
    sync_run_id: UUID
    success: bool
    processed_bookings: int
    affected_room_keys: tuple[str, ...]
    room_states_created: int
    outbox_events_created: int
    audit_events_created: int


@dataclass(frozen=True)
class RegistryRows:
    property: db.Property
    rooms_by_key: dict[str, db.Room]
    rooms_by_clock_id: dict[str, db.Room]
    domain_rooms_by_id: dict[UUID, Room]


@dataclass(frozen=True)
class AssignmentChange:
    affected_room_ids: set[UUID]
    current_room_id: UUID | None
    changed: bool
    audit_events_created: int


@dataclass(frozen=True)
class LoadedBookings:
    bookings: list[NormalizedBooking]
    ids_by_clock_booking_id: dict[str, UUID]


@dataclass(frozen=True)
class RoomRecalculationResult:
    affected_room_keys: tuple[str, ...]
    room_states_created: int
    outbox_events_created: int
    audit_events_created: int


class ClockDbSyncService:
    """Persist normalized Clock sync output and enqueue MQTT outbox events."""

    def __init__(
        self,
        *,
        session: Session,
        room_registry: RoomRegistry,
        policy: HotelPolicy,
        topics: MqttTopics | None = None,
        cursor_source: str = CLOCK_BOOKINGS_CURSOR_SOURCE,
    ) -> None:
        self._session = session
        self._room_registry = room_registry
        self._policy = policy
        self._topics = topics or MqttTopics()
        self._cursor_source = cursor_source

    def apply_sync_result(
        self,
        result: SyncRunResult,
        *,
        correlation_id: UUID | None = None,
    ) -> PersistedSyncResult:
        correlation_id = correlation_id or uuid4()
        now_utc = _to_utc(result.finished_at)

        with self._session.begin():
            registry = self._ensure_registry()
            sync_run = db.SyncRun(
                property_id=registry.property.id,
                started_at=_to_utc(result.started_at),
                finished_at=now_utc,
                status="success" if result.success else "failed",
                processed_bookings=0,
                error_classification=result.error,
                correlation_id=correlation_id,
            )
            self._session.add(sync_run)
            self._session.flush()

            if not result.success:
                return PersistedSyncResult(
                    sync_run_id=sync_run.id,
                    success=False,
                    processed_bookings=0,
                    affected_room_keys=(),
                    room_states_created=0,
                    outbox_events_created=0,
                    audit_events_created=0,
                )

            affected_room_ids: set[UUID] = set()
            audit_events_created = 0
            processed_bookings = 0

            for normalized in result.bookings:
                self._validate_property(normalized)
                booking_row, booking_changed = self._upsert_booking(
                    registry.property,
                    normalized,
                    observed_at=now_utc,
                )
                assignment_change = self._sync_assignment(
                    registry,
                    booking_row,
                    normalized,
                    observed_at=now_utc,
                    correlation_id=correlation_id,
                )
                affected_room_ids.update(assignment_change.affected_room_ids)
                audit_events_created += assignment_change.audit_events_created
                if booking_changed and assignment_change.current_room_id is not None:
                    affected_room_ids.add(assignment_change.current_room_id)
                if not normalized.has_physical_room:
                    audit_events_created += self._audit_unassigned_if_needed(
                        registry.property,
                        booking_row,
                        normalized,
                        observed_at=now_utc,
                        correlation_id=correlation_id,
                    )
                processed_bookings += 1

            recalculation = self._recalculate_rooms(
                registry,
                affected_room_ids,
                observed_at=now_utc,
                correlation_id=correlation_id,
            )
            self._advance_cursor(registry.property, result, observed_at=now_utc)
            sync_run.processed_bookings = processed_bookings

            return PersistedSyncResult(
                sync_run_id=sync_run.id,
                success=True,
                processed_bookings=processed_bookings,
                affected_room_keys=tuple(sorted(recalculation.affected_room_keys)),
                room_states_created=recalculation.room_states_created,
                outbox_events_created=recalculation.outbox_events_created,
                audit_events_created=audit_events_created + recalculation.audit_events_created,
            )

    def load_cursor_state(self) -> SyncCursorState:
        property_row = self._session.execute(
            select(db.Property).where(db.Property.key == self._room_registry.property.key)
        ).scalar_one_or_none()
        if property_row is None:
            return SyncCursorState(last_success_at=None)
        cursor = self._session.execute(
            select(db.SyncCursor).where(
                db.SyncCursor.property_id == property_row.id,
                db.SyncCursor.source == self._cursor_source,
            )
        ).scalar_one_or_none()
        if cursor is None:
            return SyncCursorState(last_success_at=None)
        return SyncCursorState(
            last_success_at=cursor.last_success_at,
            cursor_value=cursor.cursor_value,
        )

    def evaluate_all_rooms(
        self,
        *,
        now: datetime,
        correlation_id: UUID | None = None,
    ) -> PersistedSyncResult:
        correlation_id = correlation_id or uuid4()
        now_utc = _to_utc(now)
        with self._session.begin():
            registry = self._ensure_registry()
            recalculation = self._recalculate_rooms(
                registry,
                set(registry.domain_rooms_by_id),
                observed_at=now_utc,
                correlation_id=correlation_id,
            )
            return PersistedSyncResult(
                sync_run_id=uuid4(),
                success=True,
                processed_bookings=0,
                affected_room_keys=tuple(sorted(recalculation.affected_room_keys)),
                room_states_created=recalculation.room_states_created,
                outbox_events_created=recalculation.outbox_events_created,
                audit_events_created=recalculation.audit_events_created,
            )

    def evaluate_room_keys(
        self,
        *,
        room_keys: set[str],
        now: datetime,
        correlation_id: UUID | None = None,
    ) -> PersistedSyncResult:
        correlation_id = correlation_id or uuid4()
        now_utc = _to_utc(now)
        with self._session.begin():
            registry = self._ensure_registry()
            room_ids = {
                room_row.id for key, room_row in registry.rooms_by_key.items() if key in room_keys
            }
            recalculation = self._recalculate_rooms(
                registry,
                room_ids,
                observed_at=now_utc,
                correlation_id=correlation_id,
            )
            return PersistedSyncResult(
                sync_run_id=uuid4(),
                success=True,
                processed_bookings=0,
                affected_room_keys=tuple(sorted(recalculation.affected_room_keys)),
                room_states_created=recalculation.room_states_created,
                outbox_events_created=recalculation.outbox_events_created,
                audit_events_created=recalculation.audit_events_created,
            )

    def _ensure_registry(self) -> RegistryRows:
        property_row = self._session.execute(
            select(db.Property)
            .where(db.Property.key == self._room_registry.property.key)
            .with_for_update()
        ).scalar_one_or_none()
        if property_row is None:
            property_row = db.Property(
                key=self._room_registry.property.key,
                name=self._room_registry.property.name,
                timezone=self._room_registry.property.timezone,
            )
            self._session.add(property_row)
            self._session.flush()
        else:
            property_row.name = self._room_registry.property.name
            property_row.timezone = self._room_registry.property.timezone

        rooms_by_key: dict[str, db.Room] = {}
        rooms_by_clock_id: dict[str, db.Room] = {}
        domain_rooms_by_id: dict[UUID, Room] = {}
        for room in self._room_registry.rooms:
            room_row = self._session.execute(
                select(db.Room).where(
                    db.Room.property_id == property_row.id,
                    db.Room.key == room.key,
                )
            ).scalar_one_or_none()
            if room_row is None:
                room_row = db.Room(
                    property_id=property_row.id,
                    key=room.key,
                    name=room.name,
                    floor=room.floor,
                    clock_room_id=room.clock_room_id,
                    enabled=room.enabled,
                )
                self._session.add(room_row)
                self._session.flush()
            else:
                room_row.name = room.name
                room_row.floor = room.floor
                room_row.clock_room_id = room.clock_room_id
                room_row.enabled = room.enabled

            rooms_by_key[room.key] = room_row
            if room.clock_room_id:
                rooms_by_clock_id[room.clock_room_id] = room_row
            domain_rooms_by_id[room_row.id] = room

        return RegistryRows(
            property=property_row,
            rooms_by_key=rooms_by_key,
            rooms_by_clock_id=rooms_by_clock_id,
            domain_rooms_by_id=domain_rooms_by_id,
        )

    def _validate_property(self, normalized: NormalizedBooking) -> None:
        if normalized.property_id != self._room_registry.property.key:
            raise ValueError(
                "normalized booking property_id does not match configured room registry"
            )

    def _upsert_booking(
        self,
        property_row: db.Property,
        normalized: NormalizedBooking,
        *,
        observed_at: datetime,
    ) -> tuple[db.Booking, bool]:
        booking_row = self._session.execute(
            select(db.Booking).where(
                db.Booking.property_id == property_row.id,
                db.Booking.clock_booking_id == normalized.clock_booking_id,
            )
        ).scalar_one_or_none()
        is_new = booking_row is None
        if booking_row is None:
            booking_row = db.Booking(
                property_id=property_row.id,
                clock_booking_id=normalized.clock_booking_id,
                booking_status=normalized.booking_status.value,
                source_booking_status=normalized.source_booking_status,
                arrival_date=normalized.arrival_date,
                departure_date=normalized.departure_date,
                first_seen_at=_to_utc(normalized.first_seen_at or observed_at),
                last_seen_at=_to_utc(normalized.last_seen_at or observed_at),
                payload_hash=normalized.payload_hash,
            )
            self._session.add(booking_row)

        changed = is_new or booking_row.payload_hash != normalized.payload_hash
        booking_row.booking_number = normalized.booking_number
        booking_row.external_source = normalized.external_source
        booking_row.external_reference = normalized.external_reference
        booking_row.booking_status = normalized.booking_status.value
        booking_row.source_booking_status = normalized.source_booking_status
        booking_row.arrival_date = normalized.arrival_date
        booking_row.departure_date = normalized.departure_date
        booking_row.created_at = _optional_to_utc(normalized.created_at)
        booking_row.updated_at = _optional_to_utc(normalized.updated_at)
        booking_row.status_changed_at = _optional_to_utc(normalized.status_changed_at)
        booking_row.room_type_id = normalized.room_type_id
        booking_row.room_type_name = normalized.room_type_name
        booking_row.adults = normalized.adults
        booking_row.children = normalized.children
        booking_row.last_seen_at = _to_utc(normalized.last_seen_at or observed_at)
        booking_row.payload_hash = normalized.payload_hash
        booking_row.needs_attention = normalized.needs_attention
        booking_row.attention_reason = normalized.attention_reason.value
        self._session.flush()
        return booking_row, changed

    def _sync_assignment(
        self,
        registry: RegistryRows,
        booking_row: db.Booking,
        normalized: NormalizedBooking,
        *,
        observed_at: datetime,
        correlation_id: UUID,
    ) -> AssignmentChange:
        current = self._current_assignment(booking_row)
        new_identity = _assignment_identity(normalized)
        new_room = self._resolve_room(registry, normalized)
        affected_room_ids: set[UUID] = set()

        if new_identity is None:
            if current is None:
                return AssignmentChange(
                    affected_room_ids=affected_room_ids,
                    current_room_id=None,
                    changed=False,
                    audit_events_created=0,
                )
            if current.room_id is not None:
                affected_room_ids.add(current.room_id)
            current.is_current = False
            current.removed_at = observed_at
            self._session.add(
                db.AuditEvent(
                    property_id=registry.property.id,
                    room_id=current.room_id,
                    booking_id=booking_row.id,
                    event_type="physical_room_assignment_removed",
                    message="Clock booking no longer has a physical room assignment.",
                    payload={"clock_booking_id": booking_row.clock_booking_id},
                    created_at=observed_at,
                    correlation_id=correlation_id,
                )
            )
            return AssignmentChange(
                affected_room_ids=affected_room_ids,
                current_room_id=None,
                changed=True,
                audit_events_created=1,
            )

        if current is not None and _assignment_row_identity(current) == new_identity:
            current_room_id = new_room.id if new_room is not None else None
            if current.room_id != current_room_id:
                if current.room_id is not None:
                    affected_room_ids.add(current.room_id)
                if current_room_id is not None:
                    affected_room_ids.add(current_room_id)
                current.room_id = current_room_id
                return AssignmentChange(
                    affected_room_ids=affected_room_ids,
                    current_room_id=current_room_id,
                    changed=True,
                    audit_events_created=0,
                )
            return AssignmentChange(
                affected_room_ids=affected_room_ids,
                current_room_id=current.room_id,
                changed=False,
                audit_events_created=0,
            )

        if current is not None:
            current.is_current = False
            current.removed_at = observed_at
            if current.room_id is not None:
                affected_room_ids.add(current.room_id)

        assignment = db.BookingRoomAssignment(
            booking_id=booking_row.id,
            room_id=new_room.id if new_room is not None else None,
            clock_room_id=normalized.physical_room_id,
            physical_room_number=normalized.physical_room_number,
            assigned_at=observed_at,
            is_current=True,
        )
        self._session.add(assignment)
        if assignment.room_id is not None:
            affected_room_ids.add(assignment.room_id)
        self._session.add(
            db.AuditEvent(
                property_id=registry.property.id,
                room_id=assignment.room_id,
                booking_id=booking_row.id,
                event_type="physical_room_assignment_changed",
                message="Clock physical room assignment changed.",
                payload={
                    "clock_booking_id": booking_row.clock_booking_id,
                    "clock_room_id": normalized.physical_room_id,
                    "physical_room_number": normalized.physical_room_number,
                    "mapped_room": new_room.key if new_room is not None else None,
                },
                created_at=observed_at,
                correlation_id=correlation_id,
            )
        )
        audit_events_created = 1
        if new_room is None:
            self._session.add(
                db.AuditEvent(
                    property_id=registry.property.id,
                    room_id=None,
                    booking_id=booking_row.id,
                    event_type="physical_room_not_in_registry",
                    message="Clock assigned a physical room that is not in the room registry.",
                    payload={
                        "clock_booking_id": booking_row.clock_booking_id,
                        "clock_room_id": normalized.physical_room_id,
                        "physical_room_number": normalized.physical_room_number,
                    },
                    created_at=observed_at,
                    correlation_id=correlation_id,
                )
            )
            audit_events_created += 1
        return AssignmentChange(
            affected_room_ids=affected_room_ids,
            current_room_id=assignment.room_id,
            changed=True,
            audit_events_created=audit_events_created,
        )

    def _current_assignment(self, booking_row: db.Booking) -> db.BookingRoomAssignment | None:
        return self._session.execute(
            select(db.BookingRoomAssignment).where(
                db.BookingRoomAssignment.booking_id == booking_row.id,
                db.BookingRoomAssignment.is_current.is_(True),
            )
        ).scalar_one_or_none()

    def _resolve_room(
        self,
        registry: RegistryRows,
        normalized: NormalizedBooking,
    ) -> db.Room | None:
        if normalized.physical_room_id:
            room = registry.rooms_by_clock_id.get(normalized.physical_room_id)
            if room is not None:
                return room
        if normalized.physical_room_number:
            return registry.rooms_by_key.get(normalized.physical_room_number)
        return None

    def _audit_unassigned_if_needed(
        self,
        property_row: db.Property,
        booking_row: db.Booking,
        normalized: NormalizedBooking,
        *,
        observed_at: datetime,
        correlation_id: UUID,
    ) -> int:
        hotel_now = observed_at.astimezone(self._policy.property.tzinfo)
        evaluation = evaluate_unassigned_booking(normalized, hotel_now, self._policy)
        if evaluation is None:
            return 0
        self._session.add(
            db.AuditEvent(
                property_id=property_row.id,
                room_id=None,
                booking_id=booking_row.id,
                event_type="awaiting_physical_room_assignment",
                message=(
                    "Expected arrival is inside the preparation window without a physical room."
                ),
                payload={
                    "clock_booking_id": normalized.clock_booking_id,
                    "arrival": normalized.arrival_date.isoformat(),
                    "departure": normalized.departure_date.isoformat(),
                    "attention_reason": evaluation.attention_reason.value,
                },
                created_at=observed_at,
                correlation_id=correlation_id,
            )
        )
        return 1

    def _recalculate_rooms(
        self,
        registry: RegistryRows,
        affected_room_ids: set[UUID],
        *,
        observed_at: datetime,
        correlation_id: UUID,
    ) -> RoomRecalculationResult:
        if not affected_room_ids:
            return RoomRecalculationResult(
                affected_room_keys=(),
                room_states_created=0,
                outbox_events_created=0,
                audit_events_created=0,
            )

        loaded = self._load_normalized_bookings(registry.property)
        hotel_now = observed_at.astimezone(self._policy.property.tzinfo)
        affected_room_keys: list[str] = []
        room_states_created = 0
        outbox_events_created = 0
        audit_events_created = 0

        for room_id in sorted(affected_room_ids, key=str):
            room = registry.domain_rooms_by_id.get(room_id)
            room_row = self._session.get(db.Room, room_id)
            if room is None or room_row is None:
                continue
            override = self._active_override(room_id, hotel_now)
            state = evaluate_room(
                room,
                loaded.bookings,
                hotel_now,
                self._policy,
                override,
            )
            intent = derive_room_intent(
                state,
                self._policy,
                hotel_now,
                override,
                correlation_id=correlation_id,
            )
            pms_payload = _pms_state_payload(state, correlation_id=correlation_id)
            semantic_hash = _room_state_hash(state, intent)
            latest_state = self._latest_room_state(room_id)
            if latest_state is not None and latest_state.payload_hash == semantic_hash:
                continue

            if intent is not None:
                intent = intent.model_copy(
                    update={"intent_version": _next_intent_version(latest_state)}
                )

            booking_id = (
                loaded.ids_by_clock_booking_id.get(state.booking.clock_booking_id)
                if state.booking is not None
                else None
            )
            self._session.add(
                db.RoomState(
                    room_id=room_id,
                    automation_phase=state.phase.value,
                    booking_id=booking_id,
                    needs_attention=state.needs_attention,
                    attention_reason=state.attention_reason.value,
                    effective_from=_to_utc(state.effective_from),
                    expires_at=_optional_to_utc(state.expires_at),
                    intent_version=intent.intent_version if intent is not None else 0,
                    payload_hash=semantic_hash,
                    created_at=observed_at,
                )
            )
            self._session.add(
                db.OutboxEvent(
                    topic=self._topics.room_pms_state(room.key),
                    payload=pms_payload,
                    qos=1,
                    retain=True,
                    status="pending",
                    attempts=0,
                    next_attempt_at=observed_at,
                    created_at=observed_at,
                    correlation_id=correlation_id,
                )
            )
            outbox_events_created += 1
            if intent is not None:
                self._session.add(
                    db.OutboxEvent(
                        topic=self._topics.room_intent_state(room.key),
                        payload=intent.model_dump(mode="json"),
                        qos=1,
                        retain=True,
                        status="pending",
                        attempts=0,
                        next_attempt_at=observed_at,
                        created_at=observed_at,
                        correlation_id=correlation_id,
                    )
                )
                outbox_events_created += 1
            room_states_created += 1
            affected_room_keys.append(room.key)
            if state.needs_attention:
                self._session.add(
                    db.AuditEvent(
                        property_id=registry.property.id,
                        room_id=room_id,
                        booking_id=booking_id,
                        event_type="room_state_needs_attention",
                        message="Room state requires reception attention.",
                        payload={
                            "room_key": room.key,
                            "automation_phase": state.phase.value,
                            "attention_reason": state.attention_reason.value,
                        },
                        created_at=observed_at,
                        correlation_id=correlation_id,
                    )
                )
                audit_events_created += 1

        return RoomRecalculationResult(
            affected_room_keys=tuple(affected_room_keys),
            room_states_created=room_states_created,
            outbox_events_created=outbox_events_created,
            audit_events_created=audit_events_created,
        )

    def _latest_room_state(self, room_id: UUID) -> db.RoomState | None:
        return self._session.execute(
            select(db.RoomState)
            .where(db.RoomState.room_id == room_id)
            .order_by(db.RoomState.created_at.desc(), db.RoomState.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def _active_override(self, room_id: UUID, now: datetime) -> ManualOverride | None:
        row = latest_override_row(self._session, room_id)
        if row is None:
            return None
        if not override_row_is_active(row, now):
            return None
        return manual_override_from_row(row)

    def _load_normalized_bookings(self, property_row: db.Property) -> LoadedBookings:
        booking_rows = self._session.execute(
            select(db.Booking).where(db.Booking.property_id == property_row.id)
        ).scalars()
        rows = list(booking_rows)
        if not rows:
            return LoadedBookings(bookings=[], ids_by_clock_booking_id={})

        booking_ids = [row.id for row in rows]
        assignments = self._session.execute(
            select(db.BookingRoomAssignment).where(
                db.BookingRoomAssignment.booking_id.in_(booking_ids),
                db.BookingRoomAssignment.is_current.is_(True),
            )
        ).scalars()
        assignments_by_booking_id = {
            assignment.booking_id: assignment for assignment in assignments
        }
        normalized = [
            _normalized_from_row(
                property_key=property_row.key,
                booking=row,
                assignment=assignments_by_booking_id.get(row.id),
            )
            for row in rows
        ]
        return LoadedBookings(
            bookings=normalized,
            ids_by_clock_booking_id={row.clock_booking_id: row.id for row in rows},
        )

    def _advance_cursor(
        self,
        property_row: db.Property,
        result: SyncRunResult,
        *,
        observed_at: datetime,
    ) -> None:
        cursor = self._session.execute(
            select(db.SyncCursor)
            .where(
                db.SyncCursor.property_id == property_row.id,
                db.SyncCursor.source == self._cursor_source,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if cursor is None:
            cursor = db.SyncCursor(
                property_id=property_row.id,
                source=self._cursor_source,
                cursor_value=result.next_cursor.cursor_value,
                last_success_at=_optional_to_utc(result.next_cursor.last_success_at),
                updated_at=observed_at,
            )
            self._session.add(cursor)
            return

        cursor.cursor_value = result.next_cursor.cursor_value
        cursor.last_success_at = _optional_to_utc(result.next_cursor.last_success_at)
        cursor.updated_at = observed_at


def _assignment_identity(normalized: NormalizedBooking) -> tuple[str | None, str | None] | None:
    if not normalized.has_physical_room:
        return None
    return normalized.physical_room_id, normalized.physical_room_number


def _assignment_row_identity(
    assignment: db.BookingRoomAssignment,
) -> tuple[str | None, str | None]:
    return assignment.clock_room_id, assignment.physical_room_number


def _normalized_from_row(
    *,
    property_key: str,
    booking: db.Booking,
    assignment: db.BookingRoomAssignment | None,
) -> NormalizedBooking:
    return NormalizedBooking(
        property_id=property_key,
        clock_booking_id=booking.clock_booking_id,
        booking_number=booking.booking_number,
        external_source=booking.external_source,
        external_reference=booking.external_reference,
        booking_status=BookingStatus(booking.booking_status),
        source_booking_status=booking.source_booking_status,
        arrival_date=booking.arrival_date,
        departure_date=booking.departure_date,
        created_at=booking.created_at,
        updated_at=booking.updated_at,
        status_changed_at=booking.status_changed_at,
        room_type_id=booking.room_type_id,
        room_type_name=booking.room_type_name,
        physical_room_id=assignment.clock_room_id if assignment is not None else None,
        physical_room_number=assignment.physical_room_number if assignment is not None else None,
        adults=booking.adults,
        children=booking.children,
        first_seen_at=booking.first_seen_at,
        last_seen_at=booking.last_seen_at,
        payload_hash=booking.payload_hash,
        needs_attention=booking.needs_attention,
        attention_reason=AttentionReason(booking.attention_reason or AttentionReason.NONE.value),
    )


def _pms_state_payload(
    state: RoomStateEvaluation,
    *,
    correlation_id: UUID,
) -> dict[str, Any]:
    booking = state.booking
    return {
        "schema_version": 1,
        "room_key": state.room_key,
        "automation_phase": state.phase.value,
        "booking_status": booking.booking_status.value if booking is not None else None,
        "clock_booking_id": booking.clock_booking_id if booking is not None else None,
        "arrival": booking.arrival_date.isoformat() if booking is not None else None,
        "departure": booking.departure_date.isoformat() if booking is not None else None,
        "needs_attention": state.needs_attention,
        "attention_reason": state.attention_reason.value,
        "reason": state.reason,
        "effective_from": state.effective_from.isoformat(),
        "expires_at": state.expires_at.isoformat() if state.expires_at is not None else None,
        "correlation_id": str(correlation_id),
    }


def _room_state_hash(
    state: RoomStateEvaluation,
    intent: DesiredRoomIntent | None,
) -> str:
    booking = state.booking
    stable_intent = intent.stable_payload() if intent is not None else None
    if stable_intent is not None:
        stable_intent.pop("effective_from", None)
    return _stable_hash(
        {
            "room_key": state.room_key,
            "phase": state.phase.value,
            "booking": (
                {
                    "clock_booking_id": booking.clock_booking_id,
                    "booking_status": booking.booking_status.value,
                    "arrival": booking.arrival_date.isoformat(),
                    "departure": booking.departure_date.isoformat(),
                    "physical_room_id": booking.physical_room_id,
                    "physical_room_number": booking.physical_room_number,
                }
                if booking is not None
                else None
            ),
            "needs_attention": state.needs_attention,
            "attention_reason": state.attention_reason.value,
            "reason": state.reason,
            "expires_at": state.expires_at.isoformat() if state.expires_at is not None else None,
            "intent": stable_intent,
        }
    )


def _next_intent_version(latest_state: db.RoomState | None) -> int:
    if latest_state is None:
        return 1
    return latest_state.intent_version + 1


def _stable_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _optional_to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return _to_utc(value)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
