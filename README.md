# Clock PMS+ to Home Assistant Orchestrator

Hardware-neutral hotel automation orchestration for Clock PMS+ and Home Assistant.

This service treats Clock PMS+ as the source of truth for reservations and physical room assignments, derives deterministic room automation phases, publishes versioned desired room intent over MQTT, and generates Home Assistant MQTT Discovery plus reception dashboards.

## Scope

- No Booking.com API client.
- No live iNELS, RFTC-6, MUK, relay, Modbus, G301, or other hardware execution
  in Version 1. The repository includes an offline, slave-aware G301 Version G
  contract with capability validation, status-register verification, bounded
  async retries and a multi-device entrance simulator only.
- Clock endpoint paths and payload mappings are not guessed. The live adapter is gated until official docs or sandbox payloads confirm the mapping.
- Guest PII and payment data are intentionally excluded from normalized persistence, MQTT, logs, and dashboards.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pytest
ruff check .
mypy app
```

## Docker

```powershell
copy .env.example .env
docker compose up --build
```

The API exposes:

- `GET /health/live`
- `GET /health/ready`
- `GET /metrics`
- `GET /api/v1/sync/status`
- `POST /api/v1/sync/reconcile`
- `GET /api/v1/rooms`
- `GET /api/v1/rooms/{room_key}`
- `GET /api/v1/bookings/{clock_booking_id}`
- `GET /api/v1/audit`

Administrative endpoints must be deployed behind network restriction and authentication before production use.

## Runtime Status

Layer 1 runtime wiring now exists, but live Clock calls remain disabled until a
verified `ClockApiContract` is supplied from official Clock documentation or
sanitized sandbox evidence. Fixture mode can be used for end-to-end local
runtime testing with `CLOCK_CLIENT_MODE=fixture`, explicit fixture paths and
`config/clock.mapping.example.yaml`.

The FastAPI lifespan loads settings, room registry and policy, verifies database
connectivity and Alembic head, optionally starts MQTT, publishes discovery and
system state, and can run Clock sync, policy ticks and outbox worker loops when
their feature flags are enabled.

When MQTT is enabled, the service subscribes to the documented Home Assistant
field command topics, generates server-side command IDs, audits accepted and
rejected manual override commands, publishes retained `control/state`, and
reevaluates the affected room through the same transactional outbox path as
Clock sync.

The future G301 process is intentionally not enabled by a FastAPI setting. It
will be a separately runnable service with its own OT-network configuration once
the gateway mode and bench behavior are confirmed.

Timed and until-checkout manual overrides naturally return to automatic during
policy evaluation and publish default retained `control/state`. The generated
Reception dashboard is entrance-grouped and surfaces arrivals, departures,
active manual overrides, rooms needing attention, runtime readiness, MQTT
connection, outbox health, adapter/gateway health and desired-versus-reported
room state.

Adapter intent handling validates schema and validity windows, keeps separate
seen/terminal/applied version watermarks for safe MQTT redelivery, routes by
registry entrance rather than floor, publishes component-scoped reported state
and execution results, and applies per-slave cooldown so a failed indoor unit
does not keep blocking healthy units on the same entrance.

The future adapter service still needs durable watermark/cooldown persistence,
per-entrance queue scheduling that releases the bus during delayed work,
capability-profile caching and invalidation, a commissioned staleness policy,
and live gateway transport. Partial-write verification and mismatch grace
timing must be finalized from bench observations rather than guessed here.

Generate the Home Assistant dashboard with:

```powershell
.\.venv\Scripts\python.exe tools\generate_dashboard.py --rooms config\rooms.example.yaml --out homeassistant\dashboards\hotel-reception.yaml
```

For current Home Assistant releases, configure the MQTT integration through the
Home Assistant UI and install the generated dashboard YAML under
`/config/dashboards/hotel-reception.yaml`.

## Development Order

The current implementation covers the first reviewable slice: scaffold, settings validation, typed entrance-aware domain model, deterministic state machine, policy/intent generation, Clock adapter boundary, MQTT topic/discovery helpers, Home Assistant command handling, entrance-grouped dashboard generation, persistence models and migrations, transactional outbox, offline G301 Version G adapter foundation, tests, Docker Compose, and operations docs.

Before implementing live Clock endpoint behavior, update `docs/clock-api-mapping.md` with either official Clock documentation references or sanitized sandbox payloads. Do not mark the service production-ready while endpoint, pagination and physical-room mappings remain unverified.
