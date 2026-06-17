from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.clock.interface import ClockMappingRequired, ClockPage
from app.clock.normalizer import ClockFieldMapping
from app.clock.rest import ClockRestClient
from app.clock.sync import ClockSyncService, SyncCursorState, incremental_window_start
from app.settings import Settings


class OnePageClient:
    async def list_bookings(self, *, updated_since, cursor=None):
        del updated_since, cursor
        return ClockPage(
            items=[
                {
                    "id": "b1",
                    "status": "expected",
                    "arrival": "2026-12-20",
                    "departure": "2026-12-24",
                    "room_number": "214",
                }
            ]
        )

    async def list_rooms(self):
        return []


class FailingClient:
    async def list_bookings(self, *, updated_since, cursor=None):
        del updated_since, cursor
        raise RuntimeError("Clock unavailable")

    async def list_rooms(self):
        return []


def test_incremental_window_uses_overlap() -> None:
    settings = Settings(app_env="test", clock_sync_overlap_seconds=120)
    last_success = datetime(2026, 6, 17, 10, 0, tzinfo=ZoneInfo("UTC"))

    start = incremental_window_start(
        SyncCursorState(last_success_at=last_success),
        settings=settings,
        now=last_success + timedelta(minutes=5),
    )

    assert start == last_success - timedelta(seconds=120)


@pytest.mark.asyncio
async def test_successful_poll_advances_cursor() -> None:
    settings = Settings(app_env="test")
    service = ClockSyncService(
        client=OnePageClient(),
        settings=settings,
        property_id="local_stay_razlog",
        mapping=ClockFieldMapping(
            booking_id="id",
            status="status",
            arrival_date="arrival",
            departure_date="departure",
            physical_room_number="room_number",
        ),
    )
    now = datetime(2026, 6, 17, 10, 0, tzinfo=ZoneInfo("UTC"))

    result = await service.poll_once(SyncCursorState(last_success_at=None), now=now)

    assert result.success is True
    assert len(result.bookings) == 1
    assert result.next_cursor.last_success_at == now


@pytest.mark.asyncio
async def test_failed_poll_does_not_advance_cursor() -> None:
    settings = Settings(app_env="test")
    service = ClockSyncService(
        client=FailingClient(),
        settings=settings,
        property_id="local_stay_razlog",
        mapping=ClockFieldMapping(
            booking_id="id",
            status="status",
            arrival_date="arrival",
            departure_date="departure",
        ),
    )
    cursor = SyncCursorState(last_success_at=datetime(2026, 6, 17, tzinfo=ZoneInfo("UTC")))

    result = await service.poll_once(cursor, now=datetime(2026, 6, 17, 10, tzinfo=ZoneInfo("UTC")))

    assert result.success is False
    assert result.next_cursor == cursor


@pytest.mark.asyncio
async def test_live_rest_adapter_stays_disabled_without_verified_contract() -> None:
    settings = Settings(
        app_env="test",
        clock_bookings_endpoint_path="/unverified",
        clock_rooms_endpoint_path="/unverified",
        clock_endpoint_doc_reference="unverified",
    )
    client = ClockRestClient(settings)

    with pytest.raises(ClockMappingRequired, match="verified ClockApiContract"):
        await client.list_bookings(
            updated_since=datetime(2026, 6, 17, tzinfo=ZoneInfo("UTC")),
        )
