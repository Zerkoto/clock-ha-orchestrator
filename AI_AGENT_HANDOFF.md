# AI Agent Handoff For Clock HA Orchestrator

Updated: 2026-06-17

Give this file to future AI agents before asking them to work on Clock PMS+,
Home Assistant, MQTT, hotel automation, database persistence, Docker, or
deployment for this repository.

## Project Snapshot

- Local repository path: `C:\Users\zerko\Documents\GIT\clock-ha-orchestrator`.
- GitHub repository: `https://github.com/Zerkoto/clock-ha-orchestrator`.
- Visibility: public.
- Default branch: `main`.
- Initial commit: `3c22563 Initial clock HA orchestrator scaffold`.
- Project type: Python 3.12 FastAPI service for hotel HBMS / automation.
- Target property context: approximately 275 hotel apartments in Razlog,
  Bulgaria.
- Source brief: originally created from
  `D:\Projects\Klimatici\Clock PMS+ to Home Assistant Orchestration Project.docx`.

## High-Level Purpose

This repository implements a hardware-neutral integration between Clock PMS+
and Home Assistant.

Confirmed architecture:

```text
Booking.com
-> Clock PMS+
-> Custom Clock-HA Orchestrator
-> MQTT broker
-> Home Assistant
-> future hardware adapters
```

Booking.com already communicates with Clock PMS+ through Clock's native
Booking.com integration. Do not build or add a Booking.com API client.

Clock PMS+ is the source of truth for:

1. Reservations.
2. Arrival and departure dates.
3. Reservation status.
4. Physical room allocation.
5. Check-in.
6. Checkout.
7. Cancellation.
8. No-show.
9. Room moves.

Home Assistant is the reception interface and building-automation coordinator.
Reception staff will use both Clock PMS+ and a Home Assistant dashboard for
manual adjustments.

## Critical Product Rules

Do not:

1. Create a Booking.com API client.
2. Guess Clock API endpoint paths, authentication details, pagination, filter
   parameters, notification payloads, physical-room-assignment fields, or status
   values.
3. Store or publish guest PII or payment information.
4. Store guest names unless a later approved requirement explicitly adds them.
5. Treat a room type as a physical room.
6. Issue automation intent before Clock has assigned a specific physical room.
7. Put iNELS, RFTC-6, MUK, relay, TCP-controller, Modbus, G301, Alpin, or other
   hardware-specific code inside Clock ingestion or the policy engine.
8. Publish fake device success, fake actual temperature, or fabricated hardware
   state.
9. Publish MQTT directly inside the Clock synchronization transaction.
10. Require HACS or custom Home Assistant cards in Version 1.
11. Create endpoints that alter Clock reservations.

Before implementing any Clock-specific field or endpoint, cite the official
Clock documentation or record an observed sanitized sandbox payload in
`docs/clock-api-mapping.md`.

## Current Implementation

The repo currently contains the first production-quality scaffold and domain
slice:

1. Python 3.12 project with FastAPI.
2. Pydantic v2 settings and validation.
3. SQLAlchemy 2 persistence models.
4. Alembic initial migration.
5. Deterministic domain model for rooms, bookings, policy, overrides and desired
   intent.
6. Deterministic room-state machine.
7. Policy engine for hardware-neutral desired room intent.
8. Manual control command validation and temperature clamping.
9. Clock adapter protocol, fixture client, guarded REST client and sync service.
10. Clock normalizer that strips PII from payload hashes.
11. MQTT topic contract and serialization helpers.
12. Home Assistant MQTT Discovery config generation.
13. Home Assistant dashboard generator from room inventory YAML.
14. Transactional outbox publisher helper.
15. FastAPI shell endpoints.
16. Dockerfile and Docker Compose.
17. Example Mosquitto, Home Assistant, policy and room registry config.
18. Documentation under `docs/`.
19. GitHub Actions CI.
20. Unit tests.

## Important Files

Start with these:

```text
README.md
AI_AGENT_HANDOFF.md
docs/architecture.md
docs/clock-api-mapping.md
docs/mqtt-contract.md
docs/future-adapter-contract.md
docs/operations-runbook.md
pyproject.toml
docker-compose.yml
.env.example
config/policies.example.yaml
config/rooms.example.yaml
homeassistant/configuration.example.yaml
homeassistant/dashboards/hotel-reception.yaml
app/settings.py
app/main.py
app/api/routes.py
app/clock/interface.py
app/clock/rest.py
app/clock/normalizer.py
app/clock/sync.py
app/domain/models.py
app/domain/enums.py
app/domain/state_machine.py
app/policy/engine.py
app/policy/commands.py
app/mqtt/topics.py
app/mqtt/discovery.py
app/outbox/service.py
app/persistence/models.py
migrations/versions/20260617_0001_initial.py
tools/generate_dashboard.py
tests/
```

## Current Validation State

Validation last run successfully on 2026-06-17 from:

```text
C:\Users\zerko\Documents\GIT\clock-ha-orchestrator
```

Commands:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy app
```

Result:

```text
pytest: 23 passed
ruff: All checks passed
mypy: Success, no issues found in 30 source files
```

Docker was not run during the initial scaffold because Docker was not available
in the shell PATH.

## Git And Publishing State

The project was moved from:

```text
D:\Projects\Klimatici\clock-ha-orchestrator
```

to:

```text
C:\Users\zerko\Documents\GIT\clock-ha-orchestrator
```

The old project folder path no longer exists.

The GitHub repository was created as:

```text
https://github.com/Zerkoto/clock-ha-orchestrator
```

The local `main` branch tracks `origin/main`.

Useful checks:

```powershell
git status -sb
git remote -v
git log --oneline -5
```

## Clock API Status

The project intentionally does not hard-code live Clock booking or room
endpoint paths yet.

Current official-source notes are recorded in:

```text
docs/clock-api-mapping.md
```

The guarded live REST adapter in `app/clock/rest.py` requires these environment
variables before it will perform live Clock calls:

```text
CLOCK_BOOKINGS_ENDPOINT_PATH
CLOCK_ROOMS_ENDPOINT_PATH
CLOCK_ENDPOINT_DOC_REFERENCE
```

These must be filled only after official Clock documentation or sanitized
sandbox payloads confirm the exact route and mapping.

Known Clock API notes from initial research:

1. Clock provides a PMS API for hotel data such as bookings, guests, rooms and
   rates.
2. Clock points integrators to the Clock PMS+ API Docs Postman collection.
3. API access uses `api_user` and `api_key` with Digest access authentication.
4. Public docs describe region/API/subscription/account URL composition.
5. Filter operators include values such as `eq`, `not_eq`, `gt`, `gteq`, `lt`
   and `lteq`.
6. Public docs mention a 5 calls/second per API user rate limit and retrying
   `HTTP 429 Too Many Requests` with backoff.
7. Message channels can exist later, but Version 1 must remain polling-first
   with reconciliation.

Do not infer missing endpoint paths from memory or examples. Capture the exact
official reference or sandbox payload first.

## MQTT And Home Assistant Contract

Versioned MQTT prefix:

```text
hotel/v1
```

Important topics:

```text
hotel/v1/system/clock-ha-orchestrator/availability
hotel/v1/system/clock-ha-orchestrator/state
hotel/v1/rooms/{room_key}/pms/state
hotel/v1/rooms/{room_key}/intent/state
hotel/v1/rooms/{room_key}/control/set
hotel/v1/rooms/{room_key}/reported/state
```

Rules:

1. Use QoS 1 for business state.
2. Retain state topics.
3. Do not retain command topics.
4. Use Last Will and Testament.
5. Use stable client IDs.
6. Validate command payloads.
7. Reject unsupported schema versions.
8. Add correlation IDs.
9. Subscribe to Home Assistant birth/status and republish discovery after Home
   Assistant starts.
10. `reported/state` is reserved for future hardware adapters; the orchestrator
   should not fabricate it.

## Database Model

Required tables are represented in SQLAlchemy models and initial Alembic
migration:

```text
properties
rooms
bookings
booking_room_assignments
room_states
room_policy_overrides
sync_cursors
sync_runs
outbox_events
audit_events
```

Important invariants:

1. Clock booking ID is unique per property.
2. Clock physical room ID is unique per property.
3. A booking has no more than one current physical room assignment.
4. UTC is used internally.
5. Hotel policy is evaluated in Europe/Sofia.
6. Semantic duplicate updates should not create duplicate domain events.
7. Overlapping active bookings assigned to one physical room generate a conflict.

## Current Gaps And Next Useful Slice

The most useful next production slice is DB-backed synchronization and outbox
creation:

1. Implement repository/service layer for upserting normalized bookings.
2. Persist sync runs and sync cursors.
3. Do not advance cursor after partial failure.
4. Detect physical-room assignment changes.
5. Detect newly assigned rooms, assignment removal and room moves.
6. Recalculate both old and new rooms during a move.
7. Detect overlapping active bookings in a room.
8. Persist room-state changes.
9. Create outbox events inside the same DB transaction.
10. Add integration tests around PostgreSQL transaction rollback and idempotency.

Other important next work:

1. Wire API routes to persistence instead of shell responses.
2. Implement actual MQTT client lifecycle, reconnect/backoff, LWT and HA
   birth-topic discovery republish.
3. Add DB-backed Home Assistant aggregate system state.
4. Add authentication/network restrictions for administrative endpoints.
5. Harden Mosquitto config. It currently allows anonymous access for local
   development only.
6. Run Docker Compose once Docker is available.
7. Add sanitized Clock sandbox fixtures and contract tests.
8. Expand end-to-end tests for unassigned booking -> assigned room ->
   pre-arrival -> check-in -> manual override -> room move -> checkout.

## Commands For Future Agents

Local verification:

```powershell
cd C:\Users\zerko\Documents\GIT\clock-ha-orchestrator
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy app
```

Regenerate dashboard:

```powershell
.\.venv\Scripts\python.exe tools\generate_dashboard.py --rooms config\rooms.example.yaml --out homeassistant\dashboards\hotel-reception.yaml
```

Run API locally:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --reload
```

Docker, when available:

```powershell
copy .env.example .env
docker compose up --build
```

## Initiating Prompt For Next AI Agent

```text
You are taking over the `clock-ha-orchestrator` repository.

Local path:
C:\Users\zerko\Documents\GIT\clock-ha-orchestrator

GitHub repo:
https://github.com/Zerkoto/clock-ha-orchestrator

Please inspect the current repo first. Read README.md, AI_AGENT_HANDOFF.md,
docs/architecture.md, docs/clock-api-mapping.md, docs/mqtt-contract.md,
docs/future-adapter-contract.md and docs/operations-runbook.md.

This project is a Python 3.12 FastAPI service for a hotel HBMS / automation
system in Razlog, Bulgaria. It integrates Clock PMS+ with Home Assistant
through MQTT for approximately 275 apartments.

Confirmed architecture:
Booking.com -> Clock PMS+ -> Custom Clock-HA Orchestrator -> MQTT broker ->
Home Assistant -> future hardware adapters.

Critical constraints:
- Do not create a Booking.com API client.
- Do not guess Clock PMS+ endpoints, auth, pagination, filters, physical-room
  fields or status values.
- Before implementing Clock-specific fields/endpoints, cite official Clock
  docs or record sanitized sandbox payloads in docs/clock-api-mapping.md.
- Do not implement physical hardware adapters in Version 1.
- Keep iNELS, RFTC-6, MUK, relay, TCP-controller, Modbus, G301, Alpin and
  other hardware-specific code out of Clock ingestion and policy code.
- Do not store or publish guest PII or payment data.
- Room type is not a physical room.
- Never issue automation intent until Clock has assigned a physical room.
- Use PostgreSQL persistence and transactional outbox for MQTT.
- Use Home Assistant MQTT Discovery.
- Generate Home Assistant dashboards from room registry YAML.

Before editing, run:
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy app

Continue from the existing codebase rather than recreating it. The most useful
next production slice is DB-backed synchronization/upsert plus assignment-change
detection and transactional outbox event creation, unless inspection reveals a
more urgent issue.
```

