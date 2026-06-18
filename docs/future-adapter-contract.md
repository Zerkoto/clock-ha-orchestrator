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
hotel/v1/rooms/{room_key}/adapters/{adapter_key}/reported/state
hotel/v1/rooms/{room_key}/adapters/{adapter_key}/intent/result
```

Reported state and execution results identify `adapter_key` and
`handled_components`. Each adapter is the sole writer of its scoped topics.
Retaining state per adapter prevents independent HVAC, water-heater and
convector workers from overwriting one another. Home Assistant entities read
the adapter that owns their component; there is no implicit room-level state
aggregator in this foundation.

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

Shared-bus transports must include the slave/unit address on every read and
write. Traffic is parallel across independent entrances and serialized within
each entrance.

An entrance worker must derive its room and slave membership from the room
registry. It must reject unknown or disabled entrances and must not accept a
free-form room map that can route a command across entrance boundaries. Floor
is display metadata only and is never a routing key.

## Intent Version Lifecycle

Adapters track three independent per-room watermarks:

- `last_seen_version`: highest version received; only lower versions are stale.
- `last_terminal_version`: highest version with a final result that must not be
  executed again.
- `last_applied_version`: highest version confirmed through actual-state
  readback.

Seeing an intent does not make it terminal. A retryable profile read, gateway
timeout or device-offline result leaves the same version eligible for MQTT
redelivery. If a write may have reached the device, redelivery verifies the
planned actual state before deciding whether to write again. A duplicate of a
terminal version replays the cached result; the `stale` status is reserved for
versions lower than `last_seen_version`.

The adapter fingerprints the semantic payload for the current version. Reusing
one version number for a different payload is rejected as a contract violation.
The offline worker keeps this state in memory; the production adapter should
persist it so restart and reconnect behavior retains the same idempotency rules.

Adapters reject unsupported schemas and malformed HVAC states. An expired
intent is terminal without hardware access; an intent whose `effective_from`
is still in the future advances only `last_seen_version`: it must not become
terminal or applied, and equal-version redelivery remains eligible. Small
clock-skew tolerance may be configured, but timestamps must be timezone-aware.

A failed slave must enter an independent bounded exponential cooldown. Commands
for that slave fail fast during the cooldown while other slaves on the same
entrance remain eligible. Gateway-wide failures may still affect the whole
entrance. The live scheduler should avoid sleeping while it owns the entrance
bus lock and should interleave delayed verification with other ready work.

## G301 Version G Baseline

The in-repository `app.g301_adapter` package is an offline foundation only. It
contains register codecs, typed async transport boundaries, capability-aware
planning, status-register readback, bounded retries, stale-intent rejection, an
in-memory multi-slave simulator and a serialized entrance worker shell. It does
not open a gateway connection or claim production Modbus behavior until bench
commissioning confirms gateway topology, slave addressing and timing.

The adapter will run as a separate process from the FastAPI orchestrator. The
orchestrator therefore has no `G301_ADAPTER_ENABLED` switch; adapter runtime
settings belong to the future adapter executable and container.
