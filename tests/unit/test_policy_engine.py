from datetime import timedelta
from uuid import UUID

from app.domain.enums import AutomationPhase, ControlMode, ManualHvacMode
from app.domain.models import ManualOverride
from app.domain.state_machine import evaluate_room
from app.policy.commands import ManualControlCommand, command_to_override
from app.policy.engine import derive_room_intent
from tests.conftest import booking


def test_pre_arrival_intent_turns_on_hvac_and_water_heater(policy, now, room_214) -> None:
    state = evaluate_room(room_214, [booking()], now, policy)

    intent = derive_room_intent(state, policy, now)

    assert intent is not None
    assert intent.automation_phase == AutomationPhase.PRE_ARRIVAL
    assert intent.control_mode == ControlMode.AUTOMATIC
    assert intent.hvac.enabled is True
    assert intent.hvac.mode == ManualHvacMode.HEAT
    assert intent.water_heater.enabled is True


def test_intent_version_ignores_correlation_id(policy, now, room_214) -> None:
    state = evaluate_room(room_214, [booking()], now, policy)

    first = derive_room_intent(
        state,
        policy,
        now,
        correlation_id=UUID("00000000-0000-0000-0000-000000000001"),
    )
    second = derive_room_intent(
        state,
        policy,
        now,
        correlation_id=UUID("00000000-0000-0000-0000-000000000002"),
    )

    assert first is not None
    assert second is not None
    assert first.intent_version == second.intent_version


def test_manual_command_clamps_temperature(policy, now) -> None:
    command = ManualControlCommand(
        command_id=UUID("00000000-0000-0000-0000-000000000001"),
        control_mode=ControlMode.MANUAL,
        manual_hvac_mode=ManualHvacMode.HEAT,
        manual_target_temperature_c=30,
        override_duration="60",
        manual_water_heater_enabled=True,
    )

    override = command_to_override(command, policy.automation, now)

    assert override.target_temperature_c == policy.automation.occupied_maximum_target_c
    assert override.expires_at == now + timedelta(minutes=60)


def test_conflict_intent_suppresses_automation(policy, now, room_214) -> None:
    state = evaluate_room(room_214, [booking(), booking(clock_booking_id="booking-2")], now, policy)

    intent = derive_room_intent(state, policy, now)

    assert intent is not None
    assert intent.automation_phase == AutomationPhase.CONFLICT
    assert intent.control_mode == ControlMode.OFF
    assert intent.hvac.enabled is False


def test_manual_override_intent_uses_override(policy, now, room_214) -> None:
    override = ManualOverride(
        control_mode=ControlMode.MANUAL,
        hvac_mode=ManualHvacMode.COOL,
        target_temperature_c=20,
        water_heater_enabled=False,
        expires_at=now + timedelta(hours=1),
    )
    state = evaluate_room(room_214, [booking()], now, policy, override)

    intent = derive_room_intent(state, policy, now, override)

    assert intent is not None
    assert intent.control_mode == ControlMode.MANUAL
    assert intent.hvac.mode == ManualHvacMode.COOL
    assert intent.hvac.target_temperature_c == 20

