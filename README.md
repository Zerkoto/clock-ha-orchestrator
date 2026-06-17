# Clock PMS+ to Home Assistant Orchestrator

Hardware-neutral hotel automation orchestration for Clock PMS+ and Home Assistant.

This service treats Clock PMS+ as the source of truth for reservations and physical room assignments, derives deterministic room automation phases, publishes versioned desired room intent over MQTT, and generates Home Assistant MQTT Discovery plus reception dashboards.

## Scope

- No Booking.com API client.
- No direct iNELS, RFTC-6, MUK, relay, Modbus, G301, or other hardware implementation in Version 1.
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

Generate the Home Assistant dashboard with:

```powershell
.\.venv\Scripts\python.exe tools\generate_dashboard.py --rooms config\rooms.example.yaml --out homeassistant\dashboards\hotel-reception.yaml
```

For current Home Assistant releases, configure the MQTT integration through the
Home Assistant UI and install the generated dashboard YAML under
`/config/dashboards/hotel-reception.yaml`.

## Development Order

The current implementation covers the first reviewable slice: scaffold, settings validation, typed domain model, deterministic state machine, policy/intent generation, Clock adapter boundary, MQTT topic/discovery helpers, dashboard generation, persistence models, tests, Docker Compose, and operations docs.

Before implementing live Clock endpoint behavior, update `docs/clock-api-mapping.md` with either official Clock documentation references or sanitized sandbox payloads. Do not mark the service production-ready while endpoint, pagination and physical-room mappings remain unverified.
