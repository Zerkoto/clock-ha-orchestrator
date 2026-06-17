from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.clock.interface import ClockClient
from app.clock.normalizer import ClockFieldMapping, normalize_booking_payload
from app.domain.models import NormalizedBooking
from app.settings import Settings


@dataclass(frozen=True)
class SyncCursorState:
    last_success_at: datetime | None
    cursor_value: str | None = None


@dataclass(frozen=True)
class SyncRunResult:
    success: bool
    bookings: list[NormalizedBooking]
    started_at: datetime
    finished_at: datetime
    next_cursor: SyncCursorState
    error: str | None = None


def incremental_window_start(
    cursor: SyncCursorState,
    *,
    settings: Settings,
    now: datetime,
) -> datetime:
    if cursor.last_success_at is None:
        return now - timedelta(days=settings.clock_reconciliation_days_past)
    return cursor.last_success_at - timedelta(seconds=settings.clock_sync_overlap_seconds)


def reconciliation_window(settings: Settings, *, now: datetime) -> tuple[datetime, datetime]:
    return (
        now - timedelta(days=settings.clock_reconciliation_days_past),
        now + timedelta(days=settings.clock_reconciliation_days_future),
    )


class ClockSyncService:
    def __init__(
        self,
        *,
        client: ClockClient,
        settings: Settings,
        property_id: str,
        mapping: ClockFieldMapping,
    ) -> None:
        self._client = client
        self._settings = settings
        self._property_id = property_id
        self._mapping = mapping

    async def poll_once(self, cursor: SyncCursorState, *, now: datetime) -> SyncRunResult:
        started_at = now
        updated_since = incremental_window_start(cursor, settings=self._settings, now=now)
        raw_bookings: list[dict[str, object]] = []
        next_cursor = cursor.cursor_value
        try:
            while True:
                page = await self._client.list_bookings(
                    updated_since=updated_since,
                    cursor=next_cursor,
                )
                raw_bookings.extend(page.items)
                next_cursor = page.next_cursor
                if next_cursor is None:
                    break
            normalized = [
                normalize_booking_payload(
                    payload,
                    property_id=self._property_id,
                    mapping=self._mapping,
                    first_seen_at=started_at,
                    last_seen_at=started_at,
                )
                for payload in raw_bookings
            ]
            return SyncRunResult(
                success=True,
                bookings=normalized,
                started_at=started_at,
                finished_at=now,
                next_cursor=SyncCursorState(last_success_at=now, cursor_value=None),
            )
        except Exception as exc:
            return SyncRunResult(
                success=False,
                bookings=[],
                started_at=started_at,
                finished_at=now,
                next_cursor=cursor,
                error=exc.__class__.__name__,
            )

