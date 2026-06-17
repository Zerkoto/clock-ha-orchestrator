from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import UUID

from app.domain.enums import AutomationPhase, ControlMode, ManualHvacMode
from app.domain.models import (
    BinaryIntent,
    DesiredRoomIntent,
    HotelPolicy,
    HvacIntent,
    ManualOverride,
    RoomStateEvaluation,
)

SUPPRESS_AUTOMATION_PHASES = {
    AutomationPhase.AWAITING_ASSIGNMENT,
    AutomationPhase.CONFLICT,
    AutomationPhase.DISABLED,
    AutomationPhase.UNKNOWN,
}


def derive_room_intent(
    state: RoomStateEvaluation,
    policy: HotelPolicy,
    now: datetime,
    override: ManualOverride | None = None,
    correlation_id: UUID | None = None,
) -> DesiredRoomIntent | None:
    if state.room_key is None:
        return None

    if state.phase == AutomationPhase.MANUAL_OVERRIDE and override is not None:
        return _build_intent(
            state=state,
            now=now,
            control_mode=override.control_mode,
            hvac=HvacIntent(
                enabled=override.hvac_mode != ManualHvacMode.OFF,
                mode=override.hvac_mode,
                target_temperature_c=(
                    policy.automation.clamp_temperature(override.target_temperature_c)
                    if override.target_temperature_c is not None
                    else None
                ),
            ),
            water_heater=BinaryIntent(enabled=bool(override.water_heater_enabled)),
            convectors=BinaryIntent(enabled=override.hvac_mode != ManualHvacMode.OFF),
            reason=state.reason,
            correlation_id=correlation_id,
        )

    if state.phase in SUPPRESS_AUTOMATION_PHASES:
        return _build_intent(
            state=state,
            now=now,
            control_mode=ControlMode.OFF,
            hvac=HvacIntent(enabled=False, mode=ManualHvacMode.OFF),
            water_heater=BinaryIntent(enabled=False),
            convectors=BinaryIntent(enabled=False),
            reason=state.reason,
            correlation_id=correlation_id,
        )

    if state.phase == AutomationPhase.VACANT:
        return _build_intent(
            state=state,
            now=now,
            control_mode=ControlMode.AUTOMATIC,
            hvac=HvacIntent(
                enabled=True,
                mode=ManualHvacMode.HEAT,
                target_temperature_c=policy.automation.vacant_heating_setback_c,
            ),
            water_heater=BinaryIntent(enabled=False),
            convectors=BinaryIntent(enabled=False),
            reason=state.reason,
            correlation_id=correlation_id,
        )

    if state.phase in {AutomationPhase.PRE_ARRIVAL, AutomationPhase.RESERVED}:
        pre_arrival = state.phase == AutomationPhase.PRE_ARRIVAL
        return _build_intent(
            state=state,
            now=now,
            control_mode=ControlMode.AUTOMATIC,
            hvac=HvacIntent(
                enabled=pre_arrival,
                mode=ManualHvacMode.HEAT if pre_arrival else ManualHvacMode.OFF,
                target_temperature_c=(
                    policy.automation.default_heating_target_c if pre_arrival else None
                ),
            ),
            water_heater=BinaryIntent(
                enabled=pre_arrival and policy.automation.turn_on_water_heater_pre_arrival
            ),
            convectors=BinaryIntent(
                enabled=pre_arrival and policy.automation.enable_convectors_pre_arrival
            ),
            reason=state.reason,
            correlation_id=correlation_id,
        )

    if state.phase in {AutomationPhase.OCCUPIED, AutomationPhase.CHECKOUT_DUE}:
        return _build_intent(
            state=state,
            now=now,
            control_mode=ControlMode.AUTOMATIC,
            hvac=HvacIntent(
                enabled=True,
                mode=ManualHvacMode.AUTO,
                target_temperature_c=policy.automation.clamp_temperature(
                    policy.automation.default_heating_target_c
                ),
            ),
            water_heater=BinaryIntent(enabled=True),
            convectors=BinaryIntent(enabled=True),
            reason=state.reason,
            correlation_id=correlation_id,
        )

    return _build_intent(
        state=state,
        now=now,
        control_mode=ControlMode.OFF,
        hvac=HvacIntent(enabled=False, mode=ManualHvacMode.OFF),
        water_heater=BinaryIntent(enabled=False),
        convectors=BinaryIntent(enabled=False),
        reason="unhandled_phase_suppressed",
        correlation_id=correlation_id,
    )


def stable_intent_version(intent: DesiredRoomIntent) -> int:
    encoded = json.dumps(intent.stable_payload(), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def _build_intent(
    *,
    state: RoomStateEvaluation,
    now: datetime,
    control_mode: ControlMode,
    hvac: HvacIntent,
    water_heater: BinaryIntent,
    convectors: BinaryIntent,
    reason: str,
    correlation_id: UUID | None,
) -> DesiredRoomIntent:
    intent = DesiredRoomIntent(
        room_key=state.room_key or "",
        intent_version=0,
        automation_phase=state.phase,
        control_mode=control_mode,
        effective_from=state.effective_from or now,
        expires_at=state.expires_at,
        hvac=hvac,
        water_heater=water_heater,
        convectors=convectors,
        reason=reason,
        **({"correlation_id": correlation_id} if correlation_id else {}),
    )
    return intent.model_copy(update={"intent_version": stable_intent_version(intent)})
