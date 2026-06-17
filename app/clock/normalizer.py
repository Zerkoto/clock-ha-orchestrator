from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from app.domain.enums import AttentionReason, BookingStatus
from app.domain.models import NormalizedBooking

STATUS_MAP: dict[str, BookingStatus] = {
    "expected": BookingStatus.EXPECTED,
    "checked_in": BookingStatus.CHECKED_IN,
    "checked_out": BookingStatus.CHECKED_OUT,
    "canceled": BookingStatus.CANCELED,
    "no_show": BookingStatus.NO_SHOW,
}


class ClockFieldMapping(BaseModel):
    booking_id: str
    status: str
    arrival_date: str
    departure_date: str
    updated_at: str | None = None
    created_at: str | None = None
    status_changed_at: str | None = None
    booking_number: str | None = None
    external_source: str | None = None
    external_reference: str | None = None
    room_type_id: str | None = None
    room_type_name: str | None = None
    physical_room_id: str | None = None
    physical_room_number: str | None = None
    adults: str | None = None
    children: str | None = None


def normalize_booking_payload(
    payload: dict[str, Any],
    *,
    property_id: str,
    mapping: ClockFieldMapping,
    first_seen_at: datetime,
    last_seen_at: datetime,
) -> NormalizedBooking:
    source_status = str(_require(payload, mapping.status))
    status = STATUS_MAP.get(source_status, BookingStatus.UNKNOWN)
    needs_attention = status == BookingStatus.UNKNOWN

    return NormalizedBooking(
        property_id=property_id,
        clock_booking_id=str(_require(payload, mapping.booking_id)),
        booking_number=_optional_str(payload, mapping.booking_number),
        external_source=_optional_str(payload, mapping.external_source),
        external_reference=_optional_str(payload, mapping.external_reference),
        booking_status=status,
        source_booking_status=source_status,
        arrival_date=_parse_date(_require(payload, mapping.arrival_date)),
        departure_date=_parse_date(_require(payload, mapping.departure_date)),
        created_at=_optional_datetime(payload, mapping.created_at),
        updated_at=_optional_datetime(payload, mapping.updated_at),
        status_changed_at=_optional_datetime(payload, mapping.status_changed_at),
        room_type_id=_optional_str(payload, mapping.room_type_id),
        room_type_name=_optional_str(payload, mapping.room_type_name),
        physical_room_id=_optional_str(payload, mapping.physical_room_id),
        physical_room_number=_optional_str(payload, mapping.physical_room_number),
        adults=_optional_int(payload, mapping.adults),
        children=_optional_int(payload, mapping.children),
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
        payload_hash=payload_hash(payload),
        needs_attention=needs_attention,
        attention_reason=(
            AttentionReason.UNKNOWN_CLOCK_STATUS if needs_attention else AttentionReason.NONE
        ),
    )


def payload_hash(payload: dict[str, Any]) -> str:
    sanitized = _strip_pii(payload)
    encoded = json.dumps(sanitized, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _strip_pii(payload: dict[str, Any]) -> dict[str, Any]:
    pii_markers = ("guest", "email", "e_mail", "phone", "card", "address", "note", "passport")
    return {
        key: value
        for key, value in payload.items()
        if not any(marker in key.lower() for marker in pii_markers)
    }


def _require(payload: dict[str, Any], key: str) -> Any:
    value = payload.get(key)
    if value is None:
        raise ValueError(f"required Clock field missing: {key}")
    return value


def _optional_str(payload: dict[str, Any], key: str | None) -> str | None:
    if key is None or payload.get(key) is None:
        return None
    return str(payload[key])


def _optional_int(payload: dict[str, Any], key: str | None) -> int | None:
    if key is None or payload.get(key) is None:
        return None
    return int(payload[key])


def _optional_datetime(payload: dict[str, Any], key: str | None) -> datetime | None:
    if key is None or payload.get(key) is None:
        return None
    return datetime.fromisoformat(str(payload[key]).replace("Z", "+00:00"))


def _parse_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value))
