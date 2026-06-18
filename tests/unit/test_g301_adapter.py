from __future__ import annotations

import asyncio
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
from app.g301_adapter.planner import G301PlanningError, compare_readback, plan_room_intent
from app.g301_adapter.registers import (
    G301ModeLimitation,
    G301Register,
    build_device_profile,
    decode_indoor_faults,
    encode_set_temperature_c,
    parse_capabilities,
)
from app.g301_adapter.simulator import G301EntranceSimulator, G301RegisterSimulator
from app.g301_adapter.transport import G301ModbusException, G301TransportError
from app.g301_adapter.worker import G301EntranceWorker

NOW = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
CORRELATION_ID = UUID("00000000-0000-0000-0000-000000000301")
DEVICE_PROFILE = build_device_profile(
    capabilities_raw=0,
    mode_limitation_raw=G301ModeLimitation.NONE,
    upper_temperature_raw=31,
    lower_temperature_raw=16,
)


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


@pytest.mark.asyncio
async def test_planner_maps_desired_heat_intent_to_confirmed_registers() -> None:
    intent = desired_intent(
        hvac=HvacIntent(
            enabled=True,
            mode=ManualHvacMode.HEAT,
            target_temperature_c=22.5,
        )
    )

    plan = plan_room_intent(intent, slave_address=7, device_profile=DEVICE_PROFILE)

    assert [(write.address, write.value) for write in plan.writes] == [
        (G301Register.MODE, 4),
        (G301Register.SET_TEMPERATURE, 225),
        (G301Register.POWER, 1),
    ]
    simulator = G301RegisterSimulator(slave_address=7)
    observed = await simulator.apply_plan(plan)
    assert compare_readback(plan, observed) == ()
    assert [expectation.address for expectation in plan.readback_expectations] == [
        G301Register.MODE_STATUS,
        G301Register.SET_TEMPERATURE,
        G301Register.POWER_STATUS,
    ]


def test_planner_turns_disabled_hvac_into_power_off_only() -> None:
    intent = desired_intent(
        hvac=HvacIntent(enabled=False, mode=ManualHvacMode.OFF, target_temperature_c=None)
    )

    plan = plan_room_intent(intent, slave_address=7)

    assert [(write.address, write.value) for write in plan.writes] == [(G301Register.POWER, 0)]
    assert plan.readback_expectations[0].address == G301Register.POWER_STATUS


@pytest.mark.asyncio
async def test_entrance_worker_routes_operations_to_room_slave_address() -> None:
    simulator = G301EntranceSimulator(
        {
            7: G301RegisterSimulator(slave_address=7),
            8: G301RegisterSimulator(slave_address=8),
        }
    )
    worker = G301EntranceWorker(
        entrance_key="entrance_a",
        room_slave_addresses={"214": 7, "215": 8},
        client=simulator,
        retry_backoff_seconds=0,
        readback_delay_seconds=0,
    )

    result = await worker.apply_intent(
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
    assert {slave for _, slave, _ in simulator.operations} == {7}
    read_addresses = {
        address for operation, _, address in simulator.operations if operation == "read"
    }
    assert G301Register.POWER_STATUS in read_addresses
    assert G301Register.MODE_STATUS in read_addresses


def test_planner_rejects_device_mode_and_temperature_limit_violations() -> None:
    heat_prohibited = build_device_profile(
        capabilities_raw=0,
        mode_limitation_raw=G301ModeLimitation.HEAT_PROHIBITED,
        upper_temperature_raw=27,
        lower_temperature_raw=18,
    )
    with pytest.raises(G301PlanningError, match="prohibits heat"):
        plan_room_intent(
            desired_intent(
                hvac=HvacIntent(
                    enabled=True,
                    mode=ManualHvacMode.HEAT,
                    target_temperature_c=22.0,
                )
            ),
            slave_address=7,
            device_profile=heat_prohibited,
        )

    with pytest.raises(G301PlanningError, match="outside G301 device limits"):
        plan_room_intent(
            desired_intent(
                hvac=HvacIntent(
                    enabled=True,
                    mode=ManualHvacMode.COOL,
                    target_temperature_c=28.0,
                )
            ),
            slave_address=7,
            device_profile=heat_prohibited,
        )


@pytest.mark.asyncio
async def test_worker_allows_delayed_actual_state_readback() -> None:
    simulator = G301RegisterSimulator(slave_address=7, status_delay_reads=1)
    worker = G301EntranceWorker(
        entrance_key="entrance_a",
        room_slave_addresses={"214": 7},
        client=simulator,
        retry_backoff_seconds=0,
        readback_attempts=2,
        readback_delay_seconds=0,
    )

    result = await worker.apply_intent(
        desired_intent(
            hvac=HvacIntent(
                enabled=True,
                mode=ManualHvacMode.COOL,
                target_temperature_c=24.0,
            )
        )
    )

    assert result.status == "applied"


@pytest.mark.asyncio
async def test_worker_rejects_stale_or_duplicate_intent_versions() -> None:
    simulator = G301RegisterSimulator(slave_address=7)
    worker = G301EntranceWorker(
        entrance_key="entrance_a",
        room_slave_addresses={"214": 7},
        client=simulator,
        retry_backoff_seconds=0,
        readback_delay_seconds=0,
    )
    intent = desired_intent(
        hvac=HvacIntent(enabled=False, mode=ManualHvacMode.OFF, target_temperature_c=None)
    )

    assert (await worker.apply_intent(intent)).status == "applied"
    assert (await worker.apply_intent(intent)).status == "stale"


@pytest.mark.asyncio
async def test_worker_retries_transient_gateway_failure() -> None:
    simulator = G301RegisterSimulator(slave_address=7)
    client = FailFirstWriteClient(simulator)
    worker = G301EntranceWorker(
        entrance_key="entrance_a",
        room_slave_addresses={"214": 7},
        client=client,
        max_operation_attempts=2,
        retry_backoff_seconds=0,
        readback_delay_seconds=0,
    )

    result = await worker.apply_intent(
        desired_intent(
            hvac=HvacIntent(enabled=False, mode=ManualHvacMode.OFF, target_temperature_c=None)
        )
    )

    assert result.status == "applied"
    assert client.write_attempts == 2


@pytest.mark.asyncio
async def test_worker_classifies_modbus_exception_and_timeout() -> None:
    intent = desired_intent(
        hvac=HvacIntent(enabled=False, mode=ManualHvacMode.OFF, target_temperature_c=None)
    )
    modbus_worker = G301EntranceWorker(
        entrance_key="entrance_a",
        room_slave_addresses={"214": 7},
        client=FailingClient(G301ModbusException("illegal data address", exception_code=2)),
        max_operation_attempts=1,
        retry_backoff_seconds=0,
    )
    timeout_worker = G301EntranceWorker(
        entrance_key="entrance_a",
        room_slave_addresses={"214": 7},
        client=HangingClient(),
        operation_timeout_seconds=0.01,
        max_operation_attempts=1,
        retry_backoff_seconds=0,
    )

    assert (await modbus_worker.apply_intent(intent)).status == "modbus_exception"
    assert (await timeout_worker.apply_intent(intent)).status == "timeout"


@pytest.mark.asyncio
async def test_worker_serializes_commands_within_an_entrance() -> None:
    bus = G301EntranceSimulator(
        {
            7: G301RegisterSimulator(slave_address=7),
            8: G301RegisterSimulator(slave_address=8),
        }
    )
    client = ConcurrencyTrackingClient(bus)
    worker = G301EntranceWorker(
        entrance_key="entrance_a",
        room_slave_addresses={"214": 7, "215": 8},
        client=client,
        retry_backoff_seconds=0,
        readback_delay_seconds=0,
    )
    power_off = HvacIntent(enabled=False, mode=ManualHvacMode.OFF, target_temperature_c=None)

    results = await asyncio.gather(
        worker.apply_intent(desired_intent(hvac=power_off, room_key="214")),
        worker.apply_intent(desired_intent(hvac=power_off, room_key="215")),
    )

    assert [result.status for result in results] == ["applied", "applied"]
    assert client.maximum_concurrency == 1


class FailFirstWriteClient:
    def __init__(self, delegate: G301RegisterSimulator) -> None:
        self.delegate = delegate
        self.write_attempts = 0

    async def write_register(self, **kwargs) -> None:
        self.write_attempts += 1
        if self.write_attempts == 1:
            raise G301TransportError("gateway reconnecting")
        await self.delegate.write_register(**kwargs)

    async def read_holding_registers(self, **kwargs) -> list[int]:
        return await self.delegate.read_holding_registers(**kwargs)


class FailingClient:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def write_register(self, **kwargs) -> None:
        del kwargs
        raise self.error

    async def read_holding_registers(self, **kwargs) -> list[int]:
        del kwargs
        raise self.error


class HangingClient:
    async def write_register(self, **kwargs) -> None:
        del kwargs
        await asyncio.sleep(10)

    async def read_holding_registers(self, **kwargs) -> list[int]:
        del kwargs
        await asyncio.sleep(10)
        return []


class ConcurrencyTrackingClient:
    def __init__(self, delegate: G301EntranceSimulator) -> None:
        self.delegate = delegate
        self.active_operations = 0
        self.maximum_concurrency = 0

    async def write_register(self, **kwargs) -> None:
        self.active_operations += 1
        self.maximum_concurrency = max(self.maximum_concurrency, self.active_operations)
        try:
            await asyncio.sleep(0)
            await self.delegate.write_register(**kwargs)
        finally:
            self.active_operations -= 1

    async def read_holding_registers(self, **kwargs) -> list[int]:
        return await self.delegate.read_holding_registers(**kwargs)


def desired_intent(*, hvac: HvacIntent, room_key: str = "214") -> DesiredRoomIntent:
    return DesiredRoomIntent(
        room_key=room_key,
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
