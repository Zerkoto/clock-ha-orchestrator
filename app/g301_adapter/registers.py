from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from app.domain.enums import ManualHvacMode

SET_TEMPERATURE_MIN_C = 16.0
SET_TEMPERATURE_MAX_C = 31.0
IFEEL_AMBIENT_MIN_C = 0.0
IFEEL_AMBIENT_MAX_C = 50.0


class G301Register(IntEnum):
    POWER = 0x0201
    MODE = 0x0202
    SET_TEMPERATURE = 0x0203
    FAN_SPEED = 0x0204
    MODE_LIMITATION = 0x0214
    TEMPERATURE_UPPER_LIMIT = 0x0215
    TEMPERATURE_LOWER_LIMIT = 0x0216
    IFEEL_SWITCH = 0x0219
    IFEEL_AMBIENT_TEMPERATURE = 0x021A
    CAPABILITIES = 0x030E
    POWER_STATUS = 0x030F
    MODE_STATUS = 0x0310
    FAN_STATUS = 0x0311
    ACCESS_CONTROL_STATUS = 0x0315
    AMBIENT_TEMPERATURE = 0x0318
    INDOOR_FAULT_FLAG = 0x0321
    INDOOR_FAULT_BITS = 0x0322


class G301Mode(IntEnum):
    COOL = 1
    DRY = 2
    FAN = 3
    HEAT = 4
    AUTO = 5


class G301ModeLimitation(IntEnum):
    NONE = 0
    HEAT_PROHIBITED = 1
    COOL_DRY_PROHIBITED = 2


@dataclass(frozen=True)
class G301Capabilities:
    up_down_swing: bool
    left_right_swing: bool
    electric_aux_heating: bool
    self_cleaning: bool
    gentle_breeze: bool
    energy_saving: bool
    health: bool
    access_control: bool


@dataclass(frozen=True)
class G301DeviceProfile:
    capabilities: G301Capabilities
    mode_limitation: G301ModeLimitation
    lower_temperature_c: float
    upper_temperature_c: float


@dataclass(frozen=True)
class G301Fault:
    bit: int
    code: str | None
    description: str


INDOOR_FAULTS: dict[int, tuple[str | None, str]] = {
    15: ("E6", "interior fan malfunction"),
    14: ("d4", "water full fault"),
    13: ("PA", "mode conflict"),
    12: ("Fu", "anti-freeze protection"),
    11: ("b5", "interior fan drive failure"),
    10: ("Eb", "communication failure between main control board and display screen"),
    9: ("E0", "communication failure between indoor and outdoor units"),
    8: ("E1", "ambient temperature sensor fault"),
    7: (None, "reserved fault bit 7"),
    6: ("E2", "middle tube temperature sensor fault"),
    5: (None, "reserved fault bit 5"),
    4: (None, "reserved fault bit 4"),
    3: (None, "reserved fault bit 3"),
    2: (None, "EEPROM communication failure"),
    1: (None, "reserved fault bit 1"),
    0: (None, "capacity DIP switch malfunction"),
}


def parse_capabilities(raw: int) -> G301Capabilities:
    return G301Capabilities(
        up_down_swing=_bit(raw, 0),
        left_right_swing=_bit(raw, 1),
        electric_aux_heating=_bit(raw, 2),
        self_cleaning=_bit(raw, 3),
        gentle_breeze=_bit(raw, 4),
        energy_saving=_bit(raw, 5),
        health=_bit(raw, 6),
        access_control=_bit(raw, 7),
    )


def build_device_profile(
    *,
    capabilities_raw: int,
    mode_limitation_raw: int,
    upper_temperature_raw: int,
    lower_temperature_raw: int,
) -> G301DeviceProfile:
    try:
        mode_limitation = G301ModeLimitation(mode_limitation_raw)
    except ValueError as exc:
        raise ValueError(f"unsupported G301 mode limitation: {mode_limitation_raw}") from exc
    if not 16 <= lower_temperature_raw <= 25:
        raise ValueError(f"invalid G301 lower temperature limit: {lower_temperature_raw}")
    if not 26 <= upper_temperature_raw <= 31:
        raise ValueError(f"invalid G301 upper temperature limit: {upper_temperature_raw}")
    if lower_temperature_raw > upper_temperature_raw:
        raise ValueError("G301 lower temperature limit exceeds upper limit")
    return G301DeviceProfile(
        capabilities=parse_capabilities(capabilities_raw),
        mode_limitation=mode_limitation,
        lower_temperature_c=float(lower_temperature_raw),
        upper_temperature_c=float(upper_temperature_raw),
    )


def decode_indoor_faults(raw: int) -> tuple[G301Fault, ...]:
    return tuple(
        G301Fault(bit=bit, code=code, description=description)
        for bit, (code, description) in INDOOR_FAULTS.items()
        if _bit(raw, bit)
    )


def encode_set_temperature_c(value: float) -> int:
    if not SET_TEMPERATURE_MIN_C <= value <= SET_TEMPERATURE_MAX_C:
        raise ValueError(
            f"G301 set temperature must be {SET_TEMPERATURE_MIN_C:g}-{SET_TEMPERATURE_MAX_C:g} C"
        )
    return int(round(value * 10))


def decode_set_temperature_c(raw: int) -> float:
    return raw / 10.0


def encode_ifeel_ambient_temperature_c(value: float) -> int:
    if not IFEEL_AMBIENT_MIN_C <= value <= IFEEL_AMBIENT_MAX_C:
        raise ValueError(
            f"G301 iFeel ambient temperature must be {IFEEL_AMBIENT_MIN_C:g}-"
            f"{IFEEL_AMBIENT_MAX_C:g} C"
        )
    return int(round(value * 10 + 1000))


def decode_offset_temperature_c(raw: int) -> float:
    return (raw - 1000) / 10.0


def mode_from_hvac_mode(mode: ManualHvacMode) -> G301Mode | None:
    match mode:
        case ManualHvacMode.OFF:
            return None
        case ManualHvacMode.HEAT:
            return G301Mode.HEAT
        case ManualHvacMode.COOL:
            return G301Mode.COOL
        case ManualHvacMode.AUTO:
            return G301Mode.AUTO


def _bit(value: int, bit: int) -> bool:
    return bool(value & (1 << bit))
