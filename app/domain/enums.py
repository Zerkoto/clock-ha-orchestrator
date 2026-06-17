from enum import StrEnum


class BookingStatus(StrEnum):
    EXPECTED = "expected"
    CHECKED_IN = "checked_in"
    CHECKED_OUT = "checked_out"
    CANCELED = "canceled"
    NO_SHOW = "no_show"
    UNKNOWN = "unknown"


class AutomationPhase(StrEnum):
    VACANT = "vacant"
    RESERVED = "reserved"
    AWAITING_ASSIGNMENT = "awaiting_assignment"
    PRE_ARRIVAL = "pre_arrival"
    OCCUPIED = "occupied"
    CHECKOUT_DUE = "checkout_due"
    MANUAL_OVERRIDE = "manual_override"
    DISABLED = "disabled"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


class ControlMode(StrEnum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"
    OFF = "off"


class ManualHvacMode(StrEnum):
    OFF = "off"
    HEAT = "heat"
    COOL = "cool"
    AUTO = "auto"


class AttentionReason(StrEnum):
    NONE = "none"
    UNKNOWN_CLOCK_STATUS = "unknown_clock_status"
    MISSING_PHYSICAL_ROOM = "missing_physical_room"
    OVERLAPPING_ACTIVE_BOOKINGS = "overlapping_active_bookings"
    INVALID_POLICY = "invalid_policy"
    REJECTED_MANUAL_COMMAND = "rejected_manual_command"
    CLOCK_SYNC_STALE = "clock_sync_stale"

