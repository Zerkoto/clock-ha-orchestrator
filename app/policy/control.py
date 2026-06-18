from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import AutomationPhase, ControlMode, ManualHvacMode
from app.domain.models import AutomationPolicy, HotelPolicy, ManualOverride, Room, RoomRegistry
from app.mqtt.topics import MqttTopics
from app.persistence import models as db

DurationOption = str

COMMAND_SOURCE = "home_assistant_mqtt"
DEFAULT_DURATION: DurationOption = "60"
SUPPORTED_DURATIONS = {"60", "240", "720", "until_checkout"}


@dataclass(frozen=True)
class CommandProcessingResult:
    accepted: bool
    room_key: str | None
    correlation_id: UUID
    error: str | None = None


@dataclass(frozen=True)
class OverrideDraft:
    control_mode: ControlMode
    hvac_mode: ManualHvacMode
    target_temperature_c: float | None
    water_heater_enabled: bool | None
    duration: DurationOption


@dataclass(frozen=True)
class BookingBoundary:
    booking_id: UUID
    checkout_at: datetime


class RoomControlCommandService:
    def __init__(
        self,
        *,
        session: Session,
        room_registry: RoomRegistry,
        policy: HotelPolicy,
        topics: MqttTopics | None = None,
    ) -> None:
        self._session = session
        self._room_registry = room_registry
        self._hotel_policy = policy
        self._policy = policy.automation
        self._topics = topics or MqttTopics()

    def apply_mqtt_command(
        self,
        *,
        room_key: str,
        field: str,
        payload: bytes,
        now: datetime,
        correlation_id: UUID | None = None,
    ) -> CommandProcessingResult:
        correlation_id = correlation_id or uuid4()
        now_utc = _to_utc(now)
        property_row = self._ensure_property()
        room = self._room_registry.by_key().get(room_key)
        if room is None:
            self._audit_rejected(
                property_row=property_row,
                room_id=None,
                room_key=room_key,
                field=field,
                reason="room is not in the configured registry",
                observed_at=now_utc,
                correlation_id=correlation_id,
            )
            return CommandProcessingResult(
                accepted=False,
                room_key=None,
                correlation_id=correlation_id,
                error="unknown_room",
            )

        room_row = self._ensure_room(property_row, room)
        try:
            row = self._build_override_row(
                room_row=room_row,
                room=room,
                field=field,
                payload=payload,
                now=now_utc,
            )
        except ValueError as exc:
            self._audit_rejected(
                property_row=property_row,
                room_id=room_row.id,
                room_key=room.key,
                field=field,
                reason=str(exc),
                observed_at=now_utc,
                correlation_id=correlation_id,
            )
            return CommandProcessingResult(
                accepted=False,
                room_key=room.key,
                correlation_id=correlation_id,
                error=str(exc),
            )

        row.command_id = correlation_id
        self._session.add(row)
        self._session.flush()
        state_payload = control_state_payload_from_override(
            room_key=room.key,
            row=row,
            now=now_utc,
        )
        self._session.add(
            db.OutboxEvent(
                topic=self._topics.room_control_state(room.key),
                payload=state_payload,
                qos=1,
                retain=True,
                status="pending",
                attempts=0,
                next_attempt_at=now_utc,
                created_at=now_utc,
                correlation_id=correlation_id,
            )
        )
        self._session.add(
            db.AuditEvent(
                property_id=property_row.id,
                room_id=room_row.id,
                booking_id=None,
                event_type="manual_override_command_accepted",
                message="Home Assistant manual override command accepted.",
                payload={
                    "room_key": room.key,
                    "field": field,
                    "control_mode": row.control_mode,
                    "command_id": str(row.command_id),
                },
                created_at=now_utc,
                correlation_id=correlation_id,
            )
        )
        return CommandProcessingResult(
            accepted=True,
            room_key=room.key,
            correlation_id=correlation_id,
        )

    def control_state_payload(self, *, room_key: str, now: datetime) -> dict[str, Any]:
        property_row = self._session.execute(
            select(db.Property).where(db.Property.key == self._room_registry.property.key)
        ).scalar_one_or_none()
        if property_row is None:
            return default_control_state_payload(room_key=room_key, now=now)
        room_row = self._session.execute(
            select(db.Room).where(
                db.Room.property_id == property_row.id,
                db.Room.key == room_key,
            )
        ).scalar_one_or_none()
        if room_row is None:
            return default_control_state_payload(room_key=room_key, now=now)
        now_utc = _to_utc(now)
        latest = latest_override_row(self._session, room_row.id)
        latest_state = latest_room_state(self._session, room_row.id)
        if latest is not None and not override_row_is_active(latest, now_utc):
            active = False
        elif latest_state is not None:
            active = latest_state.automation_phase == AutomationPhase.MANUAL_OVERRIDE.value
        else:
            active = None
        return control_state_payload_from_override(
            room_key=room_key,
            row=latest,
            now=now_utc,
            active=active,
        )

    def _build_override_row(
        self,
        *,
        room_row: db.Room,
        room: Room,
        field: str,
        payload: bytes,
        now: datetime,
    ) -> db.RoomPolicyOverride:
        text = _payload_text(payload)
        base = self._current_draft(room_row.id, now)

        if field == "return-to-automatic":
            control_mode = ControlMode.AUTOMATIC
            hvac_mode = ManualHvacMode.OFF
            target_temperature_c = None
            water_heater_enabled = None
            duration = DEFAULT_DURATION
        elif field == "mode":
            control_mode = _control_mode(text)
            duration = base.duration
            if control_mode == ControlMode.AUTOMATIC:
                hvac_mode = ManualHvacMode.OFF
                target_temperature_c = None
                water_heater_enabled = None
            elif control_mode == ControlMode.OFF:
                hvac_mode = ManualHvacMode.OFF
                target_temperature_c = None
                water_heater_enabled = False
            else:
                hvac_mode = (
                    base.hvac_mode if base.hvac_mode != ManualHvacMode.OFF else ManualHvacMode.AUTO
                )
                target_temperature_c = (
                    base.target_temperature_c or self._policy.default_heating_target_c
                )
                water_heater_enabled = base.water_heater_enabled
        elif field == "hvac-mode":
            hvac_mode = _manual_hvac_mode(text)
            control_mode = ControlMode.MANUAL
            duration = base.duration
            target_temperature_c = (
                None
                if hvac_mode == ManualHvacMode.OFF
                else base.target_temperature_c or self._policy.default_heating_target_c
            )
            water_heater_enabled = base.water_heater_enabled
        elif field == "temperature":
            control_mode = ControlMode.MANUAL
            hvac_mode = (
                base.hvac_mode if base.hvac_mode != ManualHvacMode.OFF else ManualHvacMode.HEAT
            )
            target_temperature_c = self._policy.clamp_temperature(_temperature(text))
            water_heater_enabled = base.water_heater_enabled
            duration = base.duration
        elif field == "duration":
            if base.control_mode == ControlMode.AUTOMATIC:
                raise ValueError("duration requires an active manual or off override")
            control_mode = base.control_mode
            hvac_mode = base.hvac_mode
            target_temperature_c = base.target_temperature_c
            water_heater_enabled = base.water_heater_enabled
            duration = _duration(text, self._policy)
        elif field == "water-heater":
            control_mode = ControlMode.MANUAL
            hvac_mode = base.hvac_mode
            target_temperature_c = base.target_temperature_c
            water_heater_enabled = _boolean_payload(text)
            duration = base.duration
        else:
            raise ValueError(f"unsupported control field: {field}")

        expires_at, until_checkout = _expiry_for_duration(duration, now)
        boundary: BookingBoundary | None = None
        if control_mode == ControlMode.AUTOMATIC:
            expires_at = None
            until_checkout = False
        elif until_checkout:
            boundary = self._current_booking_boundary(room_row.id, now)
            if boundary is None:
                raise ValueError("until_checkout requires a current assigned reservation")

        return db.RoomPolicyOverride(
            room_id=room_row.id,
            booking_id=boundary.booking_id if boundary is not None else None,
            command_id=uuid4(),
            control_mode=control_mode.value,
            hvac_mode=hvac_mode.value,
            target_temperature_c=(
                self._policy.clamp_temperature(target_temperature_c)
                if target_temperature_c is not None
                else None
            ),
            water_heater_enabled=water_heater_enabled,
            starts_at=now,
            expires_at=expires_at,
            checkout_at=boundary.checkout_at if boundary is not None else None,
            until_checkout=until_checkout,
            created_by=COMMAND_SOURCE,
        )

    def _current_draft(self, room_id: UUID, now: datetime) -> OverrideDraft:
        latest = latest_override_row(self._session, room_id)
        if latest is None or latest.control_mode == ControlMode.AUTOMATIC.value:
            return default_override_draft()
        if not override_row_is_active(latest, now):
            return default_override_draft()
        return OverrideDraft(
            control_mode=ControlMode(latest.control_mode),
            hvac_mode=ManualHvacMode(latest.hvac_mode or ManualHvacMode.OFF.value),
            target_temperature_c=latest.target_temperature_c,
            water_heater_enabled=latest.water_heater_enabled,
            duration=_duration_from_row(latest),
        )

    def _ensure_property(self) -> db.Property:
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
        return property_row

    def _ensure_room(self, property_row: db.Property, room: Room) -> db.Room:
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
                entrance_key=room.entrance_key,
                floor=room.floor,
                clock_room_id=room.clock_room_id,
                enabled=room.enabled,
            )
            self._session.add(room_row)
            self._session.flush()
        else:
            room_row.name = room.name
            room_row.entrance_key = room.entrance_key
            room_row.floor = room.floor
            room_row.clock_room_id = room.clock_room_id
            room_row.enabled = room.enabled
        return room_row

    def _current_booking_boundary(
        self,
        room_id: UUID,
        now: datetime,
    ) -> BookingBoundary | None:
        latest_state = latest_room_state(self._session, room_id)
        if latest_state is None or latest_state.booking_id is None:
            return None
        if latest_state.automation_phase not in {
            AutomationPhase.MANUAL_OVERRIDE.value,
            AutomationPhase.OCCUPIED.value,
            AutomationPhase.PRE_ARRIVAL.value,
            AutomationPhase.RESERVED.value,
        }:
            return None
        booking = self._session.get(db.Booking, latest_state.booking_id)
        if booking is None:
            return None
        checkout_at = datetime.combine(
            booking.departure_date,
            self._hotel_policy.property.default_check_out_time,
            tzinfo=self._hotel_policy.property.tzinfo,
        )
        checkout_at = _to_utc(checkout_at)
        if checkout_at <= _to_utc(now):
            return None
        return BookingBoundary(booking_id=booking.id, checkout_at=checkout_at)

    def _audit_rejected(
        self,
        *,
        property_row: db.Property,
        room_id: UUID | None,
        room_key: str,
        field: str,
        reason: str,
        observed_at: datetime,
        correlation_id: UUID,
    ) -> None:
        self._session.add(
            db.AuditEvent(
                property_id=property_row.id,
                room_id=room_id,
                booking_id=None,
                event_type="manual_override_command_rejected",
                message="Home Assistant manual override command rejected.",
                payload={
                    "room_key": room_key,
                    "field": field,
                    "reason": reason,
                    "command_id": str(correlation_id),
                },
                created_at=observed_at,
                correlation_id=correlation_id,
            )
        )


def latest_override_row(session: Session, room_id: UUID) -> db.RoomPolicyOverride | None:
    return session.execute(
        select(db.RoomPolicyOverride)
        .where(db.RoomPolicyOverride.room_id == room_id)
        .order_by(db.RoomPolicyOverride.starts_at.desc(), db.RoomPolicyOverride.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def latest_room_state(session: Session, room_id: UUID) -> db.RoomState | None:
    return session.execute(
        select(db.RoomState)
        .where(db.RoomState.room_id == room_id)
        .order_by(db.RoomState.created_at.desc(), db.RoomState.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def override_row_is_active(row: db.RoomPolicyOverride, now: datetime) -> bool:
    if row.control_mode == ControlMode.AUTOMATIC.value:
        return False
    if row.until_checkout:
        if row.booking_id is None or row.checkout_at is None:
            return False
        return _to_utc(row.checkout_at) > _to_utc(now)
    if row.expires_at is None:
        return False
    return _to_utc(row.expires_at) > _to_utc(now)


def default_control_state_payload(*, room_key: str, now: datetime) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "room_key": room_key,
        "control_mode": ControlMode.AUTOMATIC.value,
        "manual_hvac_mode": ManualHvacMode.OFF.value,
        "manual_target_temperature_c": None,
        "override_duration": DEFAULT_DURATION,
        "manual_water_heater_enabled": False,
        "active": False,
        "until_checkout": False,
        "expires_at": None,
        "command_id": None,
        "updated_at": _to_utc(now).isoformat(),
    }


def control_state_payload_from_override(
    *,
    room_key: str,
    row: db.RoomPolicyOverride | None,
    now: datetime,
    active: bool | None = None,
) -> dict[str, Any]:
    if row is None:
        return default_control_state_payload(room_key=room_key, now=now)
    is_active = override_row_is_active(row, now) if active is None else active
    if not is_active:
        return default_control_state_payload(room_key=room_key, now=now)
    expires_at_source = row.expires_at or row.checkout_at
    expires_at = _to_utc(expires_at_source).isoformat() if expires_at_source else None
    return {
        "schema_version": 1,
        "room_key": room_key,
        "control_mode": row.control_mode,
        "manual_hvac_mode": row.hvac_mode or ManualHvacMode.OFF.value,
        "manual_target_temperature_c": row.target_temperature_c,
        "override_duration": _duration_from_row(row),
        "manual_water_heater_enabled": bool(row.water_heater_enabled),
        "active": row.control_mode != ControlMode.AUTOMATIC.value,
        "until_checkout": row.until_checkout,
        "expires_at": expires_at,
        "command_id": str(row.command_id),
        "updated_at": _to_utc(now).isoformat(),
    }


def default_override_draft() -> OverrideDraft:
    return OverrideDraft(
        control_mode=ControlMode.AUTOMATIC,
        hvac_mode=ManualHvacMode.OFF,
        target_temperature_c=None,
        water_heater_enabled=False,
        duration=DEFAULT_DURATION,
    )


def manual_override_from_row(
    row: db.RoomPolicyOverride,
    *,
    clock_booking_id: str | None = None,
) -> ManualOverride | None:
    if row.control_mode == ControlMode.AUTOMATIC.value:
        return None
    return ManualOverride(
        control_mode=ControlMode(row.control_mode),
        clock_booking_id=clock_booking_id,
        hvac_mode=ManualHvacMode(row.hvac_mode or ManualHvacMode.OFF.value),
        target_temperature_c=row.target_temperature_c,
        water_heater_enabled=row.water_heater_enabled,
        expires_at=_optional_to_utc(row.expires_at),
        checkout_at=_optional_to_utc(row.checkout_at),
        until_checkout=row.until_checkout,
        command_id=row.command_id,
    )


def _payload_text(payload: bytes) -> str:
    text = payload.decode("utf-8").strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1].strip()
    return text


def _control_mode(value: str) -> ControlMode:
    try:
        return ControlMode(value)
    except ValueError as exc:
        raise ValueError(f"unsupported control mode: {value}") from exc


def _manual_hvac_mode(value: str) -> ManualHvacMode:
    try:
        return ManualHvacMode(value)
    except ValueError as exc:
        raise ValueError(f"unsupported HVAC mode: {value}") from exc


def _temperature(value: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"invalid target temperature: {value}") from exc


def _duration(value: str, policy: AutomationPolicy) -> DurationOption:
    if value not in SUPPORTED_DURATIONS:
        raise ValueError(f"unsupported override duration: {value}")
    if value != "until_checkout" and int(value) > policy.manual_override_max_minutes:
        raise ValueError("manual override duration exceeds policy maximum")
    return value


def _boolean_payload(value: str) -> bool:
    normalized = value.lower()
    if normalized in {"on", "true", "1", "yes"}:
        return True
    if normalized in {"off", "false", "0", "no"}:
        return False
    raise ValueError(f"invalid boolean payload: {value}")


def _expiry_for_duration(duration: DurationOption, now: datetime) -> tuple[datetime | None, bool]:
    if duration == "until_checkout":
        return None, True
    return now + timedelta(minutes=int(duration)), False


def _duration_from_row(row: db.RoomPolicyOverride) -> DurationOption:
    if row.until_checkout:
        return "until_checkout"
    if row.expires_at is None:
        return DEFAULT_DURATION
    minutes = round((_to_utc(row.expires_at) - _to_utc(row.starts_at)).total_seconds() / 60)
    value = str(minutes)
    return value if value in SUPPORTED_DURATIONS else DEFAULT_DURATION


def _optional_to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return _to_utc(value)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
