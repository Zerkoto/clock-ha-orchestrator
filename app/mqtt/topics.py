from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MqttTopics:
    prefix: str = "hotel/v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "prefix", self.prefix.strip("/"))

    @property
    def availability(self) -> str:
        return f"{self.prefix}/system/clock-ha-orchestrator/availability"

    @property
    def system_state(self) -> str:
        return f"{self.prefix}/system/clock-ha-orchestrator/state"

    def room_pms_state(self, room_key: str) -> str:
        return f"{self.prefix}/rooms/{room_key}/pms/state"

    def room_intent_state(self, room_key: str) -> str:
        return f"{self.prefix}/rooms/{room_key}/intent/state"

    def room_intent_result(self, room_key: str) -> str:
        return f"{self.prefix}/rooms/{room_key}/intent/result"

    def room_control_set(self, room_key: str) -> str:
        return f"{self.prefix}/rooms/{room_key}/control/set"

    def room_control_state(self, room_key: str) -> str:
        return f"{self.prefix}/rooms/{room_key}/control/state"

    def room_control_mode_set(self, room_key: str) -> str:
        return f"{self.prefix}/rooms/{room_key}/control/mode/set"

    def room_control_hvac_mode_set(self, room_key: str) -> str:
        return f"{self.prefix}/rooms/{room_key}/control/hvac-mode/set"

    def room_control_temperature_set(self, room_key: str) -> str:
        return f"{self.prefix}/rooms/{room_key}/control/temperature/set"

    def room_control_duration_set(self, room_key: str) -> str:
        return f"{self.prefix}/rooms/{room_key}/control/duration/set"

    def room_control_water_heater_set(self, room_key: str) -> str:
        return f"{self.prefix}/rooms/{room_key}/control/water-heater/set"

    def room_control_return_to_automatic_set(self, room_key: str) -> str:
        return f"{self.prefix}/rooms/{room_key}/control/return-to-automatic/set"

    def room_reported_state(self, room_key: str) -> str:
        return f"{self.prefix}/rooms/{room_key}/reported/state"

    def entrance_adapter_availability(self, entrance_key: str) -> str:
        return f"{self.prefix}/entrances/{entrance_key}/adapter/availability"

    def entrance_adapter_state(self, entrance_key: str) -> str:
        return f"{self.prefix}/entrances/{entrance_key}/adapter/state"
