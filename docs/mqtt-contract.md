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

Home Assistant must never publish directly to future hardware topics.
