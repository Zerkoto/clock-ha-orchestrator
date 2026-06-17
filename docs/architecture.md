# Architecture

## Confirmed Flow

```text
Booking.com -> Clock PMS+ -> Clock HA Orchestrator -> MQTT broker -> Home Assistant -> future hardware adapters
```

Clock PMS+ remains the source of truth for reservation status, dates, check-in, checkout, cancellation, no-show and physical room allocation. Home Assistant is the reception interface and building-automation coordinator.

## Core Boundaries

- `app.clock`: Clock API access, field mapping, fixture clients and synchronization contracts.
- `app.domain`: normalized booking data, room registry, policy model and deterministic state machine.
- `app.policy`: desired room intent derivation and reception command validation.
- `app.persistence`: PostgreSQL schema and migration model.
- `app.mqtt`: versioned topic contract, serialization and Home Assistant MQTT Discovery.
- `app.dashboard`: standard Home Assistant dashboard generation from the room registry.

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

Desired room intent is not device execution. Future adapters subscribe to `hotel/v1/rooms/{room_key}/intent/state`, translate intent into their own hardware protocol, and publish reported state separately.

