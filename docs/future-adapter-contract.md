# Future Adapter Contract

Future adapters are interchangeable consumers of desired room intent. They must not require changes to Clock ingestion or the policy engine.

## Adapter Variants

- Corridor gateway adapter.
- RFTC-6 adapter.
- Wired central-controller adapter.
- Alpin/Modbus adapter.

## Required Behavior

Each adapter subscribes to:

```text
hotel/v1/rooms/{room_key}/intent/state
```

Each adapter publishes actual state separately to:

```text
hotel/v1/rooms/{room_key}/reported/state
```

Adapters must preserve:

- `room_key`
- `intent_version`
- `correlation_id`

Adapters report command failures without changing desired state. They may publish availability and hardware-specific diagnostics under their own documented topics.

