from __future__ import annotations

from datetime import date, datetime, time
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import (
    AttentionReason,
    AutomationPhase,
    BookingStatus,
    ControlMode,
    ManualHvacMode,
)

SOFIA_TZ = ZoneInfo("Europe/Sofia")


class NormalizedBooking(BaseModel):
    model_config = ConfigDict(frozen=True)

    property_id: str
    clock_booking_id: str
    booking_number: str | None = None
    external_source: str | None = None
    external_reference: str | None = None
    booking_status: BookingStatus
    source_booking_status: str
    arrival_date: date
    departure_date: date
    created_at: datetime | None = None
    updated_at: datetime | None = None
    status_changed_at: datetime | None = None
    room_type_id: str | None = None
    room_type_name: str | None = None
    physical_room_id: str | None = None
    physical_room_number: str | None = None
    adults: int | None = Field(default=None, ge=0)
    children: int | None = Field(default=None, ge=0)
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    payload_hash: str
    needs_attention: bool = False
    attention_reason: AttentionReason = AttentionReason.NONE

    @model_validator(mode="after")
    def validate_dates(self) -> NormalizedBooking:
        if self.departure_date < self.arrival_date:
            raise ValueError("departure_date cannot be before arrival_date")
        if self.booking_status == BookingStatus.UNKNOWN and not self.needs_attention:
            raise ValueError("unknown Clock status must require attention")
        return self

    @property
    def has_physical_room(self) -> bool:
        return bool(self.physical_room_id or self.physical_room_number)

    @property
    def active_for_automation(self) -> bool:
        return self.booking_status in {BookingStatus.EXPECTED, BookingStatus.CHECKED_IN}


class Entrance(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    name: str
    gateway_host: str | None = None
    gateway_port: int | None = Field(default=None, ge=1, le=65535)
    enabled: bool = True


class G301RoomMapping(BaseModel):
    model_config = ConfigDict(frozen=True)

    slave_address: int = Field(ge=1, le=255)


class Room(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    name: str
    entrance_key: str
    floor: str | None = None
    clock_room_id: str | None = None
    g301: G301RoomMapping | None = None
    enabled: bool = True


class PropertyRegistry(BaseModel):
    key: str
    name: str
    timezone: str = "Europe/Sofia"

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


class RoomRegistry(BaseModel):
    property: PropertyRegistry
    entrances: list[Entrance]
    rooms: list[Room]

    @model_validator(mode="after")
    def validate_registry(self) -> RoomRegistry:
        entrance_keys = [entrance.key for entrance in self.entrances]
        if len(entrance_keys) != len(set(entrance_keys)):
            raise ValueError("entrance keys must be unique")
        known_entrances = set(entrance_keys)
        missing_entrances = sorted(
            {room.entrance_key for room in self.rooms if room.entrance_key not in known_entrances}
        )
        if missing_entrances:
            raise ValueError(
                "room entrance_key values must reference configured entrances: "
                + ", ".join(missing_entrances)
            )

        g301_addresses = [
            (room.entrance_key, room.g301.slave_address)
            for room in self.rooms
            if room.g301 is not None
        ]
        if len(g301_addresses) != len(set(g301_addresses)):
            raise ValueError("G301 slave addresses must be unique within each entrance")
        return self

    @field_validator("rooms")
    @classmethod
    def require_unique_room_keys(cls, rooms: list[Room]) -> list[Room]:
        keys = [room.key for room in rooms]
        if len(keys) != len(set(keys)):
            raise ValueError("room keys must be unique")
        clock_ids = [room.clock_room_id for room in rooms if room.clock_room_id]
        if len(clock_ids) != len(set(clock_ids)):
            raise ValueError("clock_room_id values must be unique")
        return rooms

    def by_key(self) -> dict[str, Room]:
        return {room.key: room for room in self.rooms}

    def rooms_by_entrance(self) -> dict[str, list[Room]]:
        return {
            entrance.key: sorted(
                [room for room in self.rooms if room.entrance_key == entrance.key],
                key=lambda item: item.key,
            )
            for entrance in self.entrances
        }


class PropertyPolicy(BaseModel):
    timezone: str = "Europe/Sofia"
    default_check_in_time: time = time(hour=15)
    default_check_out_time: time = time(hour=11)

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


class AutomationPolicy(BaseModel):
    pre_arrival_lead_minutes: int = Field(default=240, ge=0)
    default_heating_target_c: float = 22.0
    default_cooling_target_c: float = 24.0
    vacant_heating_setback_c: float = 16.0
    occupied_minimum_target_c: float = 19.0
    occupied_maximum_target_c: float = 24.0
    manual_override_max_minutes: int = Field(default=720, ge=1)
    turn_on_water_heater_pre_arrival: bool = True
    enable_convectors_pre_arrival: bool = True

    @model_validator(mode="after")
    def validate_temperature_bounds(self) -> AutomationPolicy:
        if self.occupied_minimum_target_c > self.occupied_maximum_target_c:
            raise ValueError("occupied_minimum_target_c cannot exceed occupied_maximum_target_c")
        return self

    def clamp_temperature(self, value: float) -> float:
        return min(max(value, self.occupied_minimum_target_c), self.occupied_maximum_target_c)


class HotelPolicy(BaseModel):
    property: PropertyPolicy
    automation: AutomationPolicy


class ManualOverride(BaseModel):
    control_mode: ControlMode
    clock_booking_id: str | None = None
    hvac_mode: ManualHvacMode = ManualHvacMode.OFF
    target_temperature_c: float | None = None
    water_heater_enabled: bool | None = None
    expires_at: datetime | None = None
    checkout_at: datetime | None = None
    until_checkout: bool = False
    command_id: UUID = Field(default_factory=uuid4)

    def is_active(
        self,
        now: datetime,
        clock_booking_id: str | None = None,
    ) -> bool:
        if self.control_mode == ControlMode.AUTOMATIC:
            return False
        if self.until_checkout:
            if self.clock_booking_id is not None and self.clock_booking_id != clock_booking_id:
                return False
            if self.checkout_at is None:
                return False
            return now < self.checkout_at
        if self.expires_at is None:
            return False
        return now < self.expires_at


class HvacIntent(BaseModel):
    enabled: bool
    mode: ManualHvacMode
    target_temperature_c: float | None = None


class BinaryIntent(BaseModel):
    enabled: bool


class DesiredRoomIntent(BaseModel):
    schema_version: int = 1
    room_key: str
    intent_version: int
    automation_phase: AutomationPhase
    control_mode: ControlMode
    effective_from: datetime
    expires_at: datetime | None = None
    hvac: HvacIntent
    water_heater: BinaryIntent
    convectors: BinaryIntent
    reason: str
    correlation_id: UUID = Field(default_factory=uuid4)

    def stable_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload.pop("correlation_id", None)
        payload["intent_version"] = 0
        return payload


class RoomStateEvaluation(BaseModel):
    room_key: str | None
    phase: AutomationPhase
    booking: NormalizedBooking | None = None
    needs_attention: bool = False
    attention_reason: AttentionReason = AttentionReason.NONE
    reason: str
    effective_from: datetime
    expires_at: datetime | None = None
