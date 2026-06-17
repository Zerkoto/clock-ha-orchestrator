from __future__ import annotations

from collections.abc import Generator
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence import models as db
from app.runtime import AppRuntime

router = APIRouter()

registry = CollectorRegistry()
sync_lag = Gauge(
    "clock_sync_lag_seconds",
    "Seconds since the last successful Clock synchronization.",
    registry=registry,
)
pending_outbox = Gauge(
    "clock_ha_outbox_pending",
    "Pending or retrying transactional outbox rows.",
    registry=registry,
)
dead_letter_outbox = Gauge(
    "clock_ha_outbox_dead_letter",
    "Dead-lettered transactional outbox rows.",
    registry=registry,
)


def get_runtime(request: Request) -> AppRuntime:
    runtime = getattr(request.app.state, "runtime", None)
    if not isinstance(runtime, AppRuntime):
        raise HTTPException(status_code=503, detail="runtime is not initialized")
    return runtime


RuntimeDep = Annotated[AppRuntime, Depends(get_runtime)]
AdminKeyHeader = Annotated[str | None, Header(alias="X-Admin-API-Key")]


def get_session(runtime: RuntimeDep) -> Generator[Session, None, None]:
    with runtime.session_factory() as session:
        yield session


def require_admin(
    runtime: RuntimeDep,
    x_admin_api_key: AdminKeyHeader = None,
) -> None:
    expected = runtime.settings.admin_api_key
    if expected is None and runtime.settings.app_env != "production":
        return
    if expected is None or x_admin_api_key != expected.get_secret_value():
        raise HTTPException(status_code=401, detail="admin authentication required")


SessionDep = Annotated[Session, Depends(get_session)]
AdminDep = Annotated[None, Depends(require_admin)]


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/health/ready")
def ready(runtime: RuntimeDep) -> dict[str, Any]:
    if not runtime.health.ready:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "not_ready",
                "database_connected": runtime.health.database_connected,
                "migration_current": runtime.health.migration_current,
                "mqtt_connected": runtime.health.mqtt_connected,
                "workers_started": runtime.health.workers_started,
                "errors": runtime.health.errors,
            },
        )
    return {
        "status": "ready",
        "database_connected": runtime.health.database_connected,
        "migration_current": runtime.health.migration_current,
        "mqtt_connected": runtime.health.mqtt_connected,
        "workers_started": runtime.health.workers_started,
    }


@router.get("/metrics")
def metrics(
    runtime: RuntimeDep,
    session: SessionDep,
) -> Response:
    state = runtime.system_state(session)
    if state["lag_seconds"] is not None:
        sync_lag.set(float(cast(int, state["lag_seconds"])))
    pending_outbox.set(float(cast(int, state["pending_outbox"])))
    dead_letter_outbox.set(float(cast(int, state["dead_letter_outbox"])))
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)


@router.get("/api/v1/sync/status")
def sync_status(
    runtime: RuntimeDep,
    session: SessionDep,
) -> dict[str, Any]:
    return runtime.system_state(session)


@router.post("/api/v1/sync/reconcile", status_code=status.HTTP_202_ACCEPTED)
async def reconcile(
    _: AdminDep,
    runtime: RuntimeDep,
) -> dict[str, Any]:
    result = await runtime.run_sync_once()
    return {"status": "accepted", "result": result}


@router.get("/api/v1/rooms")
def rooms(session: SessionDep) -> list[dict[str, Any]]:
    rows = session.execute(select(db.Room).order_by(db.Room.floor, db.Room.key)).scalars()
    return [_room_payload(row) for row in rows]


@router.get("/api/v1/rooms/{room_key}")
def room(room_key: str, session: SessionDep) -> dict[str, Any]:
    row = session.execute(select(db.Room).where(db.Room.key == room_key)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"room not loaded: {room_key}")
    payload = _room_payload(row)
    latest_state = session.execute(
        select(db.RoomState)
        .where(db.RoomState.room_id == row.id)
        .order_by(db.RoomState.created_at.desc(), db.RoomState.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    payload["latest_state"] = _room_state_payload(latest_state)
    return payload


@router.get("/api/v1/bookings/{clock_booking_id}")
def booking(clock_booking_id: str, session: SessionDep) -> dict[str, Any]:
    row = session.execute(
        select(db.Booking).where(db.Booking.clock_booking_id == clock_booking_id)
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"booking not loaded: {clock_booking_id}")
    assignment = session.execute(
        select(db.BookingRoomAssignment).where(
            db.BookingRoomAssignment.booking_id == row.id,
            db.BookingRoomAssignment.is_current.is_(True),
        )
    ).scalar_one_or_none()
    return _booking_payload(row, assignment)


@router.get("/api/v1/audit")
def audit(
    _: AdminDep,
    session: SessionDep,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    limit = min(max(limit, 1), 500)
    offset = max(offset, 0)
    rows = session.execute(
        select(db.AuditEvent)
        .order_by(db.AuditEvent.created_at.desc(), db.AuditEvent.id.desc())
        .limit(limit)
        .offset(offset)
    ).scalars()
    return [
        {
            "id": str(row.id),
            "event_type": row.event_type,
            "message": row.message,
            "payload": row.payload,
            "created_at": row.created_at.isoformat(),
            "correlation_id": str(row.correlation_id),
        }
        for row in rows
    ]


def _room_payload(row: db.Room) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "key": row.key,
        "name": row.name,
        "floor": row.floor,
        "clock_room_id": row.clock_room_id,
        "enabled": row.enabled,
    }


def _room_state_payload(row: db.RoomState | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "automation_phase": row.automation_phase,
        "booking_id": str(row.booking_id) if row.booking_id is not None else None,
        "needs_attention": row.needs_attention,
        "attention_reason": row.attention_reason,
        "effective_from": row.effective_from.isoformat(),
        "expires_at": row.expires_at.isoformat() if row.expires_at is not None else None,
        "intent_version": row.intent_version,
        "created_at": row.created_at.isoformat(),
    }


def _booking_payload(
    row: db.Booking,
    assignment: db.BookingRoomAssignment | None,
) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "clock_booking_id": row.clock_booking_id,
        "booking_number": row.booking_number,
        "external_source": row.external_source,
        "external_reference": row.external_reference,
        "booking_status": row.booking_status,
        "source_booking_status": row.source_booking_status,
        "arrival_date": row.arrival_date.isoformat(),
        "departure_date": row.departure_date.isoformat(),
        "updated_at": row.updated_at.isoformat() if row.updated_at is not None else None,
        "needs_attention": row.needs_attention,
        "attention_reason": row.attention_reason,
        "assignment": (
            {
                "clock_room_id": assignment.clock_room_id,
                "physical_room_number": assignment.physical_room_number,
                "assigned_at": assignment.assigned_at.isoformat(),
            }
            if assignment is not None
            else None
        ),
    }
