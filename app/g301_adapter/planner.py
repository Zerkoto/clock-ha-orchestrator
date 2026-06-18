from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.domain.enums import ManualHvacMode
from app.domain.models import DesiredRoomIntent
from app.g301_adapter.registers import (
    G301DeviceProfile,
    G301ModeLimitation,
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
    readback_expectations: tuple[ReadbackExpectation, ...]


@dataclass(frozen=True)
class ReadbackExpectation:
    address: int
    expected: int
    description: str


@dataclass(frozen=True)
class ReadbackMismatch:
    address: int
    expected: int
    observed: int | None
    description: str


def plan_room_intent(
    intent: DesiredRoomIntent,
    *,
    slave_address: int,
    device_profile: G301DeviceProfile | None = None,
) -> G301Plan:
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

    if device_profile is None:
        raise G301PlanningError("enabled G301 HVAC intent requires a device capability profile")
    _validate_mode(mode, device_profile)

    writes.append(
        RegisterWrite(
            address=G301Register.MODE,
            value=int(mode),
            reason=f"desired HVAC mode is {intent.hvac.mode}",
        )
    )
    if intent.hvac.target_temperature_c is None:
        raise G301PlanningError("enabled G301 HVAC intent requires target_temperature_c")
    if not (
        device_profile.lower_temperature_c
        <= intent.hvac.target_temperature_c
        <= device_profile.upper_temperature_c
    ):
        raise G301PlanningError(
            "desired target temperature is outside G301 device limits "
            f"({device_profile.lower_temperature_c:g}-{device_profile.upper_temperature_c:g} C)"
        )
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
        ReadbackMismatch(
            address=expectation.address,
            expected=expectation.expected,
            observed=observed.get(expectation.address),
            description=expectation.description,
        )
        for expectation in plan.readback_expectations
        if observed.get(expectation.address) != expectation.expected
    )


def _plan(
    intent: DesiredRoomIntent,
    *,
    slave_address: int,
    writes: list[RegisterWrite],
) -> G301Plan:
    expectations = tuple(_readback_expectation(write) for write in writes)
    return G301Plan(
        room_key=intent.room_key,
        slave_address=slave_address,
        intent_version=intent.intent_version,
        correlation_id=intent.correlation_id,
        writes=tuple(writes),
        readback_expectations=expectations,
    )


def _readback_expectation(write: RegisterWrite) -> ReadbackExpectation:
    status_addresses = {
        int(G301Register.POWER): (
            int(G301Register.POWER_STATUS),
            "actual power status",
        ),
        int(G301Register.MODE): (
            int(G301Register.MODE_STATUS),
            "actual operating mode",
        ),
        int(G301Register.SET_TEMPERATURE): (
            int(G301Register.SET_TEMPERATURE),
            "accepted target temperature",
        ),
        int(G301Register.FAN_SPEED): (
            int(G301Register.FAN_STATUS),
            "actual fan status",
        ),
    }
    address, description = status_addresses.get(
        int(write.address),
        (int(write.address), "command register readback"),
    )
    return ReadbackExpectation(
        address=address,
        expected=write.value,
        description=description,
    )


def _validate_mode(mode: int, profile: G301DeviceProfile) -> None:
    if profile.mode_limitation == G301ModeLimitation.HEAT_PROHIBITED and mode in {
        4,
        5,
    }:
        raise G301PlanningError("G301 device prohibits heat/auto mode")
    if profile.mode_limitation == G301ModeLimitation.COOL_DRY_PROHIBITED and mode in {
        1,
        2,
        5,
    }:
        raise G301PlanningError("G301 device prohibits cool/dry/auto mode")
