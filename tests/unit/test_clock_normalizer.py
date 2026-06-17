from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.clock.normalizer import ClockFieldMapping, normalize_booking_payload, payload_hash
from app.domain.enums import AttentionReason, BookingStatus


def test_unknown_clock_status_requires_attention() -> None:
    mapping = ClockFieldMapping(
        booking_id="id",
        status="status",
        arrival_date="arrival",
        departure_date="departure",
        physical_room_number="room_number",
    )

    normalized = normalize_booking_payload(
        {
            "id": 123,
            "status": "unexpected_vendor_value",
            "arrival": "2026-12-20",
            "departure": "2026-12-24",
            "room_number": "214",
        },
        property_id="local_stay_razlog",
        mapping=mapping,
        first_seen_at=datetime.now(ZoneInfo("UTC")),
        last_seen_at=datetime.now(ZoneInfo("UTC")),
    )

    assert normalized.booking_status == BookingStatus.UNKNOWN
    assert normalized.needs_attention is True
    assert normalized.attention_reason == AttentionReason.UNKNOWN_CLOCK_STATUS


def test_payload_hash_strips_guest_pii() -> None:
    left = {"id": 1, "status": "expected", "guest_e_mail": "a@example.com"}
    right = {"id": 1, "status": "expected", "guest_e_mail": "b@example.com"}

    assert payload_hash(left) == payload_hash(right)


def test_missing_required_field_fails() -> None:
    mapping = ClockFieldMapping(
        booking_id="id",
        status="status",
        arrival_date="arrival",
        departure_date="departure",
    )

    with pytest.raises(ValueError, match="required Clock field missing"):
        normalize_booking_payload(
            {"id": 1, "status": "expected", "arrival": "2026-12-20"},
            property_id="local_stay_razlog",
            mapping=mapping,
            first_seen_at=datetime.now(ZoneInfo("UTC")),
            last_seen_at=datetime.now(ZoneInfo("UTC")),
        )
