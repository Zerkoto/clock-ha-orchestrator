from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.domain.enums import ControlMode, ManualHvacMode
from app.domain.models import AutomationPolicy, ManualOverride

OverrideDuration = Literal["60", "240", "720", "until_checkout"]


class ManualControlCommand(BaseModel):
    command_id: UUID
    control_mode: ControlMode
    manual_hvac_mode: ManualHvacMode = ManualHvacMode.OFF
    manual_target_temperature_c: float | None = None
    override_duration: OverrideDuration = "60"
    manual_water_heater_enabled: bool | None = None
    schema_version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_manual_mode(self) -> ManualControlCommand:
        if (
            self.control_mode == ControlMode.MANUAL
            and self.manual_hvac_mode != ManualHvacMode.OFF
            and self.manual_target_temperature_c is None
        ):
            raise ValueError("manual target temperature is required when manual HVAC is active")
        return self


def command_to_override(
    command: ManualControlCommand,
    policy: AutomationPolicy,
    now: datetime,
) -> ManualOverride:
    if command.schema_version != 1:
        raise ValueError("unsupported command schema version")

    if command.control_mode == ControlMode.AUTOMATIC:
        return ManualOverride(control_mode=ControlMode.AUTOMATIC, command_id=command.command_id)

    if command.control_mode == ControlMode.OFF:
        minutes = _duration_minutes(command.override_duration, policy)
        return ManualOverride(
            control_mode=ControlMode.OFF,
            expires_at=None if minutes is None else now + timedelta(minutes=minutes),
            until_checkout=minutes is None,
            command_id=command.command_id,
        )

    minutes = _duration_minutes(command.override_duration, policy)
    target = (
        policy.clamp_temperature(command.manual_target_temperature_c)
        if command.manual_target_temperature_c is not None
        else None
    )
    return ManualOverride(
        control_mode=ControlMode.MANUAL,
        hvac_mode=command.manual_hvac_mode,
        target_temperature_c=target,
        water_heater_enabled=command.manual_water_heater_enabled,
        expires_at=None if minutes is None else now + timedelta(minutes=minutes),
        until_checkout=minutes is None,
        command_id=command.command_id,
    )


def _duration_minutes(duration: OverrideDuration, policy: AutomationPolicy) -> int | None:
    if duration == "until_checkout":
        return None
    minutes = int(duration)
    if minutes > policy.manual_override_max_minutes:
        raise ValueError("manual override duration exceeds policy maximum")
    return minutes
