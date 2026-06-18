from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.domain.enums import ManualHvacMode
from app.domain.models import DesiredRoomIntent
from app.g301_adapter.registers import (
    G301Register,
    encode_set_temperature_c,
    mode_from_hvac_mode,
)


class G301PlanningError(ValueError):
    pass


@dataclass(frozen=True)
class RegisterWrite:
    address: int
    value: int
    reason: str


@dataclass(frozen=True)
class G301Plan:
    room_key: str
    slave_address: int
    intent_version: int
    correlation_id: UUID
    writes: tuple[RegisterWrite, ...]
    expected_readback: dict[int, int]


@dataclass(frozen=True)
class ReadbackMismatch:
    address: int
    expected: int
    observed: int | None


def plan_room_intent(intent: DesiredRoomIntent, *, slave_address: int) -> G301Plan:
    if not 1 <= slave_address <= 255:
        raise G301PlanningError("G301 slave_address must be in the confirmed 1-255 range")

    writes: list[RegisterWrite] = []
    if not intent.hvac.enabled or intent.hvac.mode == ManualHvacMode.OFF:
        writes.append(
            RegisterWrite(
                address=G301Register.POWER,
                value=0,
                reason="desired HVAC is disabled",
            )
        )
        return _plan(intent, slave_address=slave_address, writes=writes)

    mode = mode_from_hvac_mode(intent.hvac.mode)
    if mode is None:
        raise G301PlanningError(f"unsupported enabled HVAC mode: {intent.hvac.mode}")

    writes.append(
        RegisterWrite(
            address=G301Register.MODE,
            value=int(mode),
            reason=f"desired HVAC mode is {intent.hvac.mode}",
        )
    )
    if intent.hvac.target_temperature_c is None:
        raise G301PlanningError("enabled G301 HVAC intent requires target_temperature_c")
    writes.append(
        RegisterWrite(
            address=G301Register.SET_TEMPERATURE,
            value=encode_set_temperature_c(intent.hvac.target_temperature_c),
            reason="desired HVAC target temperature",
        )
    )
    writes.append(
        RegisterWrite(
            address=G301Register.POWER,
            value=1,
            reason="desired HVAC is enabled",
        )
    )
    return _plan(intent, slave_address=slave_address, writes=writes)


def compare_readback(plan: G301Plan, observed: dict[int, int]) -> tuple[ReadbackMismatch, ...]:
    return tuple(
        ReadbackMismatch(address=address, expected=expected, observed=observed.get(address))
        for address, expected in sorted(plan.expected_readback.items())
        if observed.get(address) != expected
    )


def _plan(
    intent: DesiredRoomIntent,
    *,
    slave_address: int,
    writes: list[RegisterWrite],
) -> G301Plan:
    expected = {write.address: write.value for write in writes}
    return G301Plan(
        room_key=intent.room_key,
        slave_address=slave_address,
        intent_version=intent.intent_version,
        correlation_id=intent.correlation_id,
        writes=tuple(writes),
        expected_readback=expected,
    )
