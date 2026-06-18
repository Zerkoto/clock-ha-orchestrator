# Future Adapter Contract

Future adapters are interchangeable consumers of desired room intent. They must not require changes to Clock ingestion or the policy engine.

## Adapter Variants

- Corridor gateway adapter.
- RFTC-6 adapter.
- Wired central-controller adapter.
- G301 Modbus adapter.
- Alpin/Modbus adapter.

## Required Behavior

Each adapter subscribes to:

```text
hotel/v1/rooms/{room_key}/intent/state
```

Each adapter publishes actual state and execution results separately to:

```text
hotel/v1/rooms/{room_key}/reported/state
hotel/v1/rooms/{room_key}/intent/result
```

Adapters must preserve:

- `room_key`
- `intent_version`
- `correlation_id`

Entrance-scoped adapters also publish health under:

```text
hotel/v1/entrances/{entrance_key}/adapter/availability
hotel/v1/entrances/{entrance_key}/adapter/state
```

Adapters report command failures without changing desired state. They may publish
hardware-specific diagnostics under their own documented topics, but Home
Assistant must not publish directly to hardware topics.

## G301 Version G Baseline

The in-repository `app.g301_adapter` package is an offline foundation only. It
contains register codecs, a safe planner, readback comparison, an in-memory
simulator and a worker shell. It does not open a gateway connection or claim
production Modbus behavior until bench commissioning confirms gateway topology,
slave addressing and timing.
