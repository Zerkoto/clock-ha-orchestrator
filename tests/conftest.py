from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.domain.enums import BookingStatus
from app.domain.models import AutomationPolicy, HotelPolicy, NormalizedBooking, PropertyPolicy, Room


@pytest.fixture
def policy() -> HotelPolicy:
    return HotelPolicy(property=PropertyPolicy(), automation=AutomationPolicy())


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 12, 20, 12, 0, tzinfo=ZoneInfo("Europe/Sofia"))


@pytest.fixture
def room_214() -> Room:
    return Room(
        key="214",
        name="Apartment 214",
        entrance_key="entrance_a",
        floor="2",
        clock_room_id="clock-room-214",
    )


def booking(
    *,
    status: BookingStatus = BookingStatus.EXPECTED,
    arrival: date = date(2026, 12, 20),
    departure: date = date(2026, 12, 24),
    room_id: str | None = "clock-room-214",
    room_number: str | None = "214",
    clock_booking_id: str = "booking-1",
) -> NormalizedBooking:
    return NormalizedBooking(
        property_id="local_stay_razlog",
        clock_booking_id=clock_booking_id,
        booking_status=status,
        source_booking_status=status.value,
        arrival_date=arrival,
        departure_date=departure,
        physical_room_id=room_id,
        physical_room_number=room_number,
        first_seen_at=datetime(2026, 6, 17, tzinfo=ZoneInfo("UTC")),
        last_seen_at=datetime(2026, 6, 17, tzinfo=ZoneInfo("UTC")),
        payload_hash="abc",
        needs_attention=status == BookingStatus.UNKNOWN,
        attention_reason="unknown_clock_status" if status == BookingStatus.UNKNOWN else "none",
    )
