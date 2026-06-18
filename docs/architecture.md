# Architecture

## Confirmed Flow

```text
Booking.com -> Clock PMS+ -> Clock HA Orchestrator -> MQTT broker -> G301 adapter -> entrance gateways
                                                        -> Home Assistant reception dashboard
```

Clock PMS+ remains the source of truth for reservation status, dates, check-in, checkout, cancellation, no-show and physical room allocation. Home Assistant is the reception interface and building-automation coordinator.

## Core Boundaries

- `app.clock`: Clock API access, field mapping, fixture clients and synchronization contracts.
- `app.domain`: normalized booking data, room registry, policy model and deterministic state machine.
- `app.policy`: desired room intent derivation and reception command validation.
- `app.persistence`: PostgreSQL schema and migration model.
- `app.mqtt`: versioned topic contract, serialization and Home Assistant MQTT Discovery.
- `app.dashboard`: standard Home Assistant dashboard generation from the room registry.
- `app.g301_adapter`: offline G301 Version G codecs, slave-aware async transport
  contract, capability-aware planner, actual-state readback and multi-slave
  simulator. Live gateway transport remains disabled until commissioning.

## Transactional Outbox

Clock synchronization must not publish MQTT from inside the booking transaction. The intended write path is:

1. Begin a database transaction.
2. Upsert normalized Clock data.
3. Detect assignment changes and room moves.
4. Recalculate affected rooms.
5. Persist room states and outbox messages.
6. Commit.
7. Publish pending outbox messages.
8. Mark successful publishes as completed.

## Hardware Neutrality

Desired room intent is not device execution. Adapters subscribe to `hotel/v1/rooms/{room_key}/intent/state`, translate intent into their own hardware protocol, and publish adapter-scoped reported state and execution results without mutating desired state. Each adapter is the sole writer of its retained scope; this foundation does not define a competing shared `reported/state` writer or an implicit aggregator.

## Entrance-Based Registry

Room routing is entrance-based. Each room has a required `entrance_key`; `floor`
is optional display metadata only. The final five production entrance names,
gateway addresses and room-to-G301 slave mapping must be supplied by the project
commissioning process before live hardware execution is enabled.

Legacy rows migrate to the explicit `legacy_unassigned` entrance rather than
deriving routing from floor. Adapter workers refuse unknown or disabled
entrances and derive enabled room/slave membership from the registry.

The recommended deployment keeps the G301 adapter separate from Clock
synchronization. The adapter consumes MQTT desired intent, performs protocol
translation, publishes room reported state, publishes intent execution results
and exposes per-entrance adapter/gateway health.

There is no G301 enable switch in the orchestrator runtime. The live adapter
will have a separate executable/container and OT-network settings after bench
testing identifies the gateway transport mode.
