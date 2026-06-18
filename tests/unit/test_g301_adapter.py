from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.domain.enums import AutomationPhase, ControlMode, ManualHvacMode
from app.domain.models import (
    BinaryIntent,
    DesiredRoomIntent,
    Entrance,
    G301RoomMapping,
    HvacIntent,
    PropertyRegistry,
    Room,
    RoomRegistry,
)
from app.g301_adapter.planner import compare_readback, plan_room_intent
from app.g301_adapter.registers import (
    G301Register,
    decode_indoor_faults,
    encode_set_temperature_c,
    parse_capabilities,
)
from app.g301_adapter.simulator import G301RegisterSimulator
from app.g301_adapter.worker import G301EntranceWorker

NOW = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
CORRELATION_ID = UUID("00000000-0000-0000-0000-000000000301")


def test_room_registry_validates_entrance_and_g301_slave_addresses() -> None:
    with pytest.raises(ValueError, match="G301 slave addresses"):
        RoomRegistry(
            property=PropertyRegistry(key="local_stay_razlog", name="Local Stay Hotel & Suites"),
            entrances=[Entrance(key="entrance_a", name="Entrance A")],
            rooms=[
                Room(
                    key="101",
                    name="Apartment 101",
                    entrance_key="entrance_a",
                    g301=G301RoomMapping(slave_address=1),
                ),
                Room(
                    key="102",
                    name="Apartment 102",
                    entrance_key="entrance_a",
                    g301=G301RoomMapping(slave_address=1),
                ),
            ],
        )


def test_g301_register_codecs_and_fault_decoding() -> None:
    assert encode_set_temperature_c(22.5) == 225

    capabilities = parse_capabilities(0b1010_0101)
    assert capabilities.up_down_swing is True
    assert capabilities.electric_aux_heating is True
    assert capabilities.energy_saving is True
    assert capabilities.access_control is True

    faults = decode_indoor_faults((1 << 13) | (1 << 8))
    assert [(fault.bit, fault.code) for fault in faults] == [(13, "PA"), (8, "E1")]


def test_planner_maps_desired_heat_intent_to_confirmed_registers() -> None:
    intent = desired_intent(
        hvac=HvacIntent(
            enabled=True,
            mode=ManualHvacMode.HEAT,
            target_temperature_c=22.5,
        )
    )

    plan = plan_room_intent(intent, slave_address=7)

    assert [(write.address, write.value) for write in plan.writes] == [
        (G301Register.MODE, 4),
        (G301Register.SET_TEMPERATURE, 225),
        (G301Register.POWER, 1),
    ]
    simulator = G301RegisterSimulator(slave_address=7)
    observed = simulator.apply_plan(plan)
    assert compare_readback(plan, observed) == ()


def test_planner_turns_disabled_hvac_into_power_off_only() -> None:
    intent = desired_intent(
        hvac=HvacIntent(enabled=False, mode=ManualHvacMode.OFF, target_temperature_c=None)
    )

    plan = plan_room_intent(intent, slave_address=7)

    assert [(write.address, write.value) for write in plan.writes] == [(G301Register.POWER, 0)]


def test_entrance_worker_applies_plan_through_register_client() -> None:
    simulator = G301RegisterSimulator(slave_address=7)
    worker = G301EntranceWorker(
        entrance_key="entrance_a",
        room_slave_addresses={"214": 7},
        client=simulator,
    )

    result = worker.apply_intent(
        desired_intent(
            hvac=HvacIntent(
                enabled=True,
                mode=ManualHvacMode.COOL,
                target_temperature_c=24.0,
            )
        )
    )

    assert result.status == "applied"
    assert result.room_key == "214"
    assert [write.address for write in result.register_writes] == [
        "0x0202",
        "0x0203",
        "0x0201",
    ]


def desired_intent(*, hvac: HvacIntent) -> DesiredRoomIntent:
    return DesiredRoomIntent(
        room_key="214",
        intent_version=3,
        automation_phase=AutomationPhase.OCCUPIED,
        control_mode=ControlMode.AUTOMATIC,
        effective_from=NOW,
        hvac=hvac,
        water_heater=BinaryIntent(enabled=False),
        convectors=BinaryIntent(enabled=False),
        reason="test",
        correlation_id=CORRELATION_ID,
    )
