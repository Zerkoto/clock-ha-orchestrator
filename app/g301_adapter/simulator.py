from __future__ import annotations

from collections.abc import Mapping

from app.g301_adapter.planner import G301Plan
from app.g301_adapter.registers import G301Register, encode_set_temperature_c
from app.g301_adapter.transport import G301DeviceOffline


class G301RegisterSimulator:
    def __init__(
        self,
        *,
        slave_address: int,
        initial: dict[int, int] | None = None,
        status_delay_reads: int = 0,
    ) -> None:
        if not 1 <= slave_address <= 255:
            raise ValueError("G301 slave_address must be in the confirmed 1-255 range")
        self.slave_address = slave_address
        if status_delay_reads < 0:
            raise ValueError("status_delay_reads cannot be negative")
        self.status_delay_reads = status_delay_reads
        self._registers = _default_registers()
        self._pending_status: dict[int, tuple[int, int]] = {}
        if initial:
            self._registers.update(initial)

    async def read_holding_registers(
        self,
        *,
        slave_address: int,
        address: int,
        count: int,
    ) -> list[int]:
        self._require_slave(slave_address)
        if count < 1:
            raise ValueError("count must be at least 1")
        values = [self._registers.get(address + offset, 0) for offset in range(count)]
        self._advance_pending_status(address=address, count=count)
        return values

    async def write_register(
        self,
        *,
        slave_address: int,
        address: int,
        value: int,
    ) -> None:
        self._require_slave(slave_address)
        if not 0 <= value <= 0xFFFF:
            raise ValueError("Modbus register values must fit in one unsigned word")
        self._registers[address] = value
        self._mirror_control_to_status(address, value)

    async def apply_plan(self, plan: G301Plan) -> dict[int, int]:
        if plan.slave_address != self.slave_address:
            raise ValueError("plan slave_address does not match simulator slave_address")
        for write in plan.writes:
            await self.write_register(
                slave_address=plan.slave_address,
                address=write.address,
                value=write.value,
            )
        return {
            expectation.address: (
                await self.read_holding_registers(
                    slave_address=plan.slave_address,
                    address=expectation.address,
                    count=1,
                )
            )[0]
            for expectation in plan.readback_expectations
        }

    def snapshot(self) -> dict[int, int]:
        return dict(self._registers)

    def _mirror_control_to_status(self, address: int, value: int) -> None:
        if address == G301Register.POWER:
            self._set_status(int(G301Register.POWER_STATUS), value)
        elif address == G301Register.MODE:
            self._set_status(int(G301Register.MODE_STATUS), value)

    def _set_status(self, address: int, value: int) -> None:
        if self.status_delay_reads:
            self._pending_status[address] = (value, self.status_delay_reads)
        else:
            self._registers[address] = value

    def _advance_pending_status(self, *, address: int, count: int) -> None:
        for pending_address in range(address, address + count):
            pending = self._pending_status.get(pending_address)
            if pending is None:
                continue
            value, remaining_reads = pending
            remaining_reads -= 1
            if remaining_reads <= 0:
                self._registers[pending_address] = value
                del self._pending_status[pending_address]
            else:
                self._pending_status[pending_address] = (value, remaining_reads)

    def _require_slave(self, slave_address: int) -> None:
        if slave_address != self.slave_address:
            raise G301DeviceOffline(f"G301 slave {slave_address} is not present")


class G301EntranceSimulator:
    def __init__(self, devices: Mapping[int, G301RegisterSimulator]) -> None:
        self.devices = dict(devices)
        self.operations: list[tuple[str, int, int]] = []

    async def read_holding_registers(
        self,
        *,
        slave_address: int,
        address: int,
        count: int,
    ) -> list[int]:
        self.operations.append(("read", slave_address, address))
        return await self._device(slave_address).read_holding_registers(
            slave_address=slave_address,
            address=address,
            count=count,
        )

    async def write_register(
        self,
        *,
        slave_address: int,
        address: int,
        value: int,
    ) -> None:
        self.operations.append(("write", slave_address, address))
        await self._device(slave_address).write_register(
            slave_address=slave_address,
            address=address,
            value=value,
        )

    def _device(self, slave_address: int) -> G301RegisterSimulator:
        try:
            return self.devices[slave_address]
        except KeyError as exc:
            raise G301DeviceOffline(f"G301 slave {slave_address} is not present") from exc


def _default_registers() -> dict[int, int]:
    return {
        int(G301Register.POWER): 0,
        int(G301Register.MODE): 0,
        int(G301Register.SET_TEMPERATURE): encode_set_temperature_c(22.0),
        int(G301Register.MODE_LIMITATION): 0,
        int(G301Register.TEMPERATURE_UPPER_LIMIT): 31,
        int(G301Register.TEMPERATURE_LOWER_LIMIT): 16,
        int(G301Register.CAPABILITIES): 0,
        int(G301Register.POWER_STATUS): 0,
        int(G301Register.MODE_STATUS): 0,
        int(G301Register.FAN_STATUS): 0,
        int(G301Register.INDOOR_FAULT_FLAG): 0,
        int(G301Register.INDOOR_FAULT_BITS): 0,
    }
