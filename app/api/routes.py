from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest

router = APIRouter()

registry = CollectorRegistry()
sync_lag = Gauge(
    "clock_sync_lag_seconds",
    "Seconds since the last successful Clock synchronization.",
    registry=registry,
)


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/health/ready")
def ready() -> dict[str, str]:
    return {"status": "ready"}


@router.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)


@router.get("/api/v1/sync/status")
def sync_status() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "not_configured",
        "last_attempt_at": None,
        "last_success_at": None,
        "lag_seconds": None,
        "rooms_loaded": 0,
        "active_bookings": 0,
        "unassigned_arrivals": 0,
        "room_conflicts": 0,
        "updated_at": datetime.now(UTC).isoformat(),
    }


@router.post("/api/v1/sync/reconcile", status_code=status.HTTP_202_ACCEPTED)
def reconcile() -> dict[str, str]:
    return {
        "status": "accepted",
        "message": "Reconciliation job scheduling is wired after persistence services are enabled.",
    }


@router.get("/api/v1/rooms")
def rooms() -> list[dict[str, Any]]:
    return []


@router.get("/api/v1/rooms/{room_key}")
def room(room_key: str) -> dict[str, Any]:
    raise HTTPException(status_code=404, detail=f"room not loaded: {room_key}")


@router.get("/api/v1/bookings/{clock_booking_id}")
def booking(clock_booking_id: str) -> dict[str, Any]:
    raise HTTPException(status_code=404, detail=f"booking not loaded: {clock_booking_id}")


@router.get("/api/v1/audit")
def audit() -> list[dict[str, Any]]:
    return []

