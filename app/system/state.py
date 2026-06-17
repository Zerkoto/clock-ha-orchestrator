from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.enums import AutomationPhase, BookingStatus
from app.persistence import models as db


def build_system_state(
    session: Session,
    *,
    property_key: str,
    now: datetime,
    mqtt_connected: bool,
    mqtt_required: bool = True,
) -> dict[str, Any]:
    property_row = session.execute(
        select(db.Property).where(db.Property.key == property_key)
    ).scalar_one_or_none()
    if property_row is None:
        return _empty_state(now=now, mqtt_connected=mqtt_connected)

    last_run = session.execute(
        select(db.SyncRun)
        .where(db.SyncRun.property_id == property_row.id)
        .order_by(db.SyncRun.started_at.desc(), db.SyncRun.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    last_success = session.execute(
        select(db.SyncRun)
        .where(db.SyncRun.property_id == property_row.id, db.SyncRun.status == "success")
        .order_by(db.SyncRun.finished_at.desc(), db.SyncRun.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    latest_states = _latest_room_states(session)
    hotel_now = now.astimezone(ZoneInfo(property_row.timezone))
    room_conflicts = sum(
        1 for state in latest_states if state.automation_phase == AutomationPhase.CONFLICT.value
    )
    active_manual_overrides = sum(
        1
        for state in latest_states
        if state.automation_phase == AutomationPhase.MANUAL_OVERRIDE.value
    )
    rooms_needing_attention = sum(1 for state in latest_states if state.needs_attention)
    pending_outbox = _count_outbox(session, "pending", "retrying", "publishing")
    dead_letter_outbox = _count_outbox(session, "dead_letter")
    lag_seconds = (
        int((now - last_success.finished_at).total_seconds())
        if last_success is not None and last_success.finished_at is not None
        else None
    )

    return {
        "schema_version": 1,
        "status": _system_status(
            mqtt_connected=mqtt_connected,
            mqtt_required=mqtt_required,
            last_success_seen=last_success is not None,
            room_conflicts=room_conflicts,
            rooms_needing_attention=rooms_needing_attention,
            pending_outbox=pending_outbox,
            dead_letter_outbox=dead_letter_outbox,
        ),
        "version": "0.1.0",
        "last_attempt_at": last_run.started_at.isoformat() if last_run is not None else None,
        "last_success_at": (
            last_success.finished_at.isoformat()
            if last_success is not None and last_success.finished_at is not None
            else None
        ),
        "sync_duration_seconds": _sync_duration_seconds(last_success),
        "lag_seconds": lag_seconds,
        "mqtt_connected": mqtt_connected,
        "rooms_loaded": _count(
            session,
            select(db.Room).where(db.Room.property_id == property_row.id),
        ),
        "checked_in_rooms": _count_bookings(session, property_row.id, BookingStatus.CHECKED_IN),
        "expected_rooms": _count_bookings(session, property_row.id, BookingStatus.EXPECTED),
        "arrivals_today": _count_arrivals(session, property_row.id, hotel_now),
        "departures_today": _count_departures(session, property_row.id, hotel_now),
        "unassigned_arrivals": _count_unassigned_arrivals(session, property_row.id),
        "room_conflicts": room_conflicts,
        "active_manual_overrides": active_manual_overrides,
        "rooms_needing_attention": rooms_needing_attention,
        "pending_outbox": pending_outbox,
        "dead_letter_outbox": dead_letter_outbox,
        "updated_at": now.isoformat(),
    }


def _empty_state(*, now: datetime, mqtt_connected: bool) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "starting",
        "version": "0.1.0",
        "last_attempt_at": None,
        "last_success_at": None,
        "sync_duration_seconds": None,
        "lag_seconds": None,
        "mqtt_connected": mqtt_connected,
        "rooms_loaded": 0,
        "checked_in_rooms": 0,
        "expected_rooms": 0,
        "arrivals_today": 0,
        "departures_today": 0,
        "unassigned_arrivals": 0,
        "room_conflicts": 0,
        "active_manual_overrides": 0,
        "rooms_needing_attention": 0,
        "pending_outbox": 0,
        "dead_letter_outbox": 0,
        "updated_at": now.isoformat(),
    }


def _latest_room_states(session: Session) -> list[db.RoomState]:
    ranked = select(
        db.RoomState.id.label("id"),
        func.row_number()
        .over(
            partition_by=db.RoomState.room_id,
            order_by=(db.RoomState.created_at.desc(), db.RoomState.id.desc()),
        )
        .label("rank"),
    ).subquery()
    return list(
        session.execute(
            select(db.RoomState)
            .join(ranked, db.RoomState.id == ranked.c.id)
            .where(ranked.c.rank == 1)
        ).scalars()
    )


def _system_status(
    *,
    mqtt_connected: bool,
    mqtt_required: bool,
    last_success_seen: bool,
    room_conflicts: int,
    rooms_needing_attention: int,
    pending_outbox: int,
    dead_letter_outbox: int,
) -> str:
    if dead_letter_outbox:
        return "error"
    if (mqtt_required and not mqtt_connected) or not last_success_seen:
        return "starting"
    if pending_outbox:
        return "degraded"
    if room_conflicts or rooms_needing_attention:
        return "attention"
    return "online"


def _sync_duration_seconds(sync_run: db.SyncRun | None) -> int | None:
    if sync_run is None or sync_run.finished_at is None:
        return None
    return int((sync_run.finished_at - sync_run.started_at).total_seconds())


def _count(session: Session, statement: Any) -> int:
    return len(list(session.execute(statement).scalars()))


def _count_bookings(session: Session, property_id: Any, status: BookingStatus) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(db.Booking)
            .where(
                db.Booking.property_id == property_id,
                db.Booking.booking_status == status.value,
            )
        )
        or 0
    )


def _count_arrivals(session: Session, property_id: Any, now: datetime) -> int:
    today = now.date()
    return (
        session.scalar(
            select(func.count())
            .select_from(db.Booking)
            .where(
                db.Booking.property_id == property_id,
                db.Booking.arrival_date == today,
            )
        )
        or 0
    )


def _count_departures(session: Session, property_id: Any, now: datetime) -> int:
    today = now.date()
    return (
        session.scalar(
            select(func.count())
            .select_from(db.Booking)
            .where(
                db.Booking.property_id == property_id,
                db.Booking.departure_date == today,
            )
        )
        or 0
    )


def _count_unassigned_arrivals(session: Session, property_id: Any) -> int:
    current_assignment_exists = (
        select(db.BookingRoomAssignment.id)
        .where(
            db.BookingRoomAssignment.booking_id == db.Booking.id,
            db.BookingRoomAssignment.is_current.is_(True),
        )
        .exists()
    )
    return (
        session.scalar(
            select(func.count())
            .select_from(db.Booking)
            .where(
                db.Booking.property_id == property_id,
                db.Booking.booking_status == BookingStatus.EXPECTED.value,
                ~current_assignment_exists,
            )
        )
        or 0
    )


def _count_outbox(session: Session, *statuses: str) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(db.OutboxEvent)
            .where(db.OutboxEvent.status.in_(statuses))
        )
        or 0
    )
