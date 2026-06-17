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

    def room_control_set(self, room_key: str) -> str:
        return f"{self.prefix}/rooms/{room_key}/control/set"

    def room_reported_state(self, room_key: str) -> str:
        return f"{self.prefix}/rooms/{room_key}/reported/state"
