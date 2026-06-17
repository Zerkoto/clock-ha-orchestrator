# MQTT Contract

Prefix: `hotel/v1`

All business state uses QoS 1. Retained state topics are retained; command topics are not retained. The orchestrator must use a stable client ID and Last Will and Testament.

## Topics

```text
hotel/v1/system/clock-ha-orchestrator/availability
hotel/v1/system/clock-ha-orchestrator/state
hotel/v1/rooms/{room_key}/pms/state
hotel/v1/rooms/{room_key}/intent/state
hotel/v1/rooms/{room_key}/control/state
hotel/v1/rooms/{room_key}/control/mode/set
hotel/v1/rooms/{room_key}/control/hvac-mode/set
hotel/v1/rooms/{room_key}/control/temperature/set
hotel/v1/rooms/{room_key}/control/duration/set
hotel/v1/rooms/{room_key}/control/water-heater/set
hotel/v1/rooms/{room_key}/control/return-to-automatic/set
hotel/v1/rooms/{room_key}/reported/state
```

`reported/state` is reserved for future adapters and is not published by this service in Version 1.

## Desired Intent

The desired intent payload is hardware-neutral and must not imply equipment execution.

```json
{
  "schema_version": 1,
  "room_key": "214",
  "intent_version": 17,
  "automation_phase": "pre_arrival",
  "control_mode": "automatic",
  "effective_from": "2026-12-20T11:00:00+02:00",
  "expires_at": "2026-12-24T11:00:00+02:00",
  "hvac": {
    "enabled": true,
    "mode": "heat",
    "target_temperature_c": 22.0
  },
  "water_heater": {
    "enabled": true
  },
  "convectors": {
    "enabled": true
  },
  "reason": "expected_arrival_inside_preparation_window",
  "correlation_id": "00000000-0000-0000-0000-000000000000"
}
```

## Commands

Reception commands are accepted only on field-specific control topics:

```text
hotel/v1/rooms/{room_key}/control/mode/set
hotel/v1/rooms/{room_key}/control/hvac-mode/set
hotel/v1/rooms/{room_key}/control/temperature/set
hotel/v1/rooms/{room_key}/control/duration/set
hotel/v1/rooms/{room_key}/control/water-heater/set
hotel/v1/rooms/{room_key}/control/return-to-automatic/set
```

The orchestrator generates command UUIDs server-side, validates and audits
accepted/rejected commands, and publishes authoritative control state to:

```text
hotel/v1/rooms/{room_key}/control/state
```

Accepted payloads are simple Home Assistant command values:

- `control/mode/set`: `automatic`, `manual` or `off`
- `control/hvac-mode/set`: `off`, `heat`, `cool` or `auto`
- `control/temperature/set`: numeric Celsius target, clamped by policy
- `control/duration/set`: `60`, `240`, `720` or `until_checkout`
- `control/water-heater/set`: `on` or `off`
- `control/return-to-automatic/set`: `return`

The latest override command for a room is authoritative. A return-to-automatic
command prevents older manual rows from becoming active again. Expired timed
overrides also return the room to automatic policy rather than reviving older
commands.

`until_checkout` is accepted only when the latest evaluated room state has a
current assigned reservation and is not already checkout-due, conflicting,
unknown or vacant. The accepted override is bound to that booking and stores its
exact checkout boundary at command time; it must not be re-evaluated against a
later occupant of the same room. When a timed or until-checkout override
naturally ends during policy evaluation, the orchestrator writes a
system-generated automatic override row and publishes default retained
`control/state` so Home Assistant controls do not remain stale.

`control/state` is retained and has no guest PII:

```json
{
  "schema_version": 1,
  "room_key": "214",
  "control_mode": "manual",
  "manual_hvac_mode": "heat",
  "manual_target_temperature_c": 21.5,
  "override_duration": "60",
  "manual_water_heater_enabled": false,
  "active": true,
  "until_checkout": false,
  "expires_at": "2026-12-20T11:05:00+00:00",
  "command_id": "00000000-0000-0000-0000-000000000000",
  "updated_at": "2026-12-20T10:05:00+00:00"
}
```

Home Assistant must never publish directly to future hardware topics.
