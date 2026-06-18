from __future__ import annotations

from app.g301_adapter.planner import G301Plan
from app.g301_adapter.registers import G301Register, encode_set_temperature_c


class G301RegisterSimulator:
    def __init__(self, *, slave_address: int, initial: dict[int, int] | None = None) -> None:
        if not 1 <= slave_address <= 255:
            raise ValueError("G301 slave_address must be in the confirmed 1-255 range")
        self.slave_address = slave_address
        self._registers = _default_registers()
        if initial:
            self._registers.update(initial)

    def read_holding_registers(self, address: int, count: int) -> list[int]:
        if count < 1:
            raise ValueError("count must be at least 1")
        return [self._registers.get(address + offset, 0) for offset in range(count)]

    def write_register(self, address: int, value: int) -> None:
        if not 0 <= value <= 0xFFFF:
            raise ValueError("Modbus register values must fit in one unsigned word")
        self._registers[address] = value
        self._mirror_control_to_status(address, value)

    def apply_plan(self, plan: G301Plan) -> dict[int, int]:
        if plan.slave_address != self.slave_address:
            raise ValueError("plan slave_address does not match simulator slave_address")
        for write in plan.writes:
            self.write_register(write.address, write.value)
        return {
            address: self.read_holding_registers(address, 1)[0]
            for address in plan.expected_readback
        }

    def snapshot(self) -> dict[int, int]:
        return dict(self._registers)

    def _mirror_control_to_status(self, address: int, value: int) -> None:
        if address == G301Register.POWER:
            self._registers[int(G301Register.POWER_STATUS)] = value
        elif address == G301Register.MODE:
            self._registers[int(G301Register.MODE_STATUS)] = value
        elif address == G301Register.SET_TEMPERATURE:
            self._registers[int(G301Register.SET_TEMPERATURE)] = value


def _default_registers() -> dict[int, int]:
    return {
        int(G301Register.POWER): 0,
        int(G301Register.MODE): 0,
        int(G301Register.SET_TEMPERATURE): encode_set_temperature_c(22.0),
        int(G301Register.CAPABILITIES): 0,
        int(G301Register.POWER_STATUS): 0,
        int(G301Register.MODE_STATUS): 0,
        int(G301Register.FAN_STATUS): 0,
        int(G301Register.INDOOR_FAULT_FLAG): 0,
        int(G301Register.INDOOR_FAULT_BITS): 0,
    }
