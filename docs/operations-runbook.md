# Operations Runbook

## Time

- Store application timestamps in UTC.
- Evaluate hotel policy and "today" counters in `Europe/Sofia` for Razlog,
  Bulgaria.
- Keep host and containers synchronized with NTP.

## Secrets

- Use environment variables or a secrets manager.
- Do not commit production `.env` files.
- Never log Clock API secrets, authorization headers, payment data or guest PII.
- Change `SECRET_KEY`, `ADMIN_API_KEY`, database passwords and MQTT passwords
  before production.

## Startup

Run migrations before or during orchestrator startup:

```bash
alembic upgrade head
```

The container image runs `alembic upgrade head` before starting Uvicorn. Do not
claim a Docker Compose deployment is production-ready until the environment has
real secrets, Mosquitto credentials and the live Clock contract is verified.

## Home Assistant

Configure the MQTT integration through the current Home Assistant UI. The
example `homeassistant/configuration.example.yaml` only registers the generated
dashboard file.

Regenerate and install the dashboard:

```powershell
.\.venv\Scripts\python.exe tools\generate_dashboard.py --rooms config\rooms.example.yaml --out homeassistant\dashboards\hotel-reception.yaml
```

Copy or mount the generated YAML to `/config/dashboards/hotel-reception.yaml`.
The dashboard is grouped by entrance, not by floor. Floor remains optional
display metadata in the registry.

Manual override controls publish only to the field-specific
`hotel/v1/rooms/{room_key}/control/.../set` topics. The orchestrator generates
server-side command IDs, audits accepted and rejected commands, and publishes
retained `control/state`. Use the dashboard controls; do not publish directly
to future hardware adapter topics.

Adapter-reported room state appears under
`hotel/v1/rooms/{room_key}/adapters/{adapter_key}/reported/state`, execution results under
`hotel/v1/rooms/{room_key}/adapters/{adapter_key}/intent/result`, and entrance adapter health under
`hotel/v1/entrances/{entrance_key}/adapter/state`. The orchestrator publishes
Discovery metadata for these entities, but the adapter is responsible for the
actual state payloads.

Each adapter is the only writer of its adapter-scoped retained state and result
topics. The current Home Assistant HVAC entities read the `g301` scope. Add
future component entities against their owning adapter scope; do not let
multiple adapters publish a shared room-level retained document.

Keep the policy scheduler enabled in production. It is responsible for natural
time transitions, including manual override expiry and until-checkout return to
automatic mode. The generated dashboard exposes runtime-ready, MQTT-connected,
policy-scheduler and outbox-worker monitors so disabled workers are visible to
Reception.

## Mosquitto

Anonymous access is disabled. Create a local password file and ACL file before
running the broker:

```bash
cp mosquitto/config/acl.example mosquitto/config/acl
docker run --rm -it -v "$PWD/mosquitto/config:/config" eclipse-mosquitto:2 \
  mosquitto_passwd -c /config/passwords clock_ha_orchestrator
```

Add separate users for Home Assistant and future adapters. Do not commit the
generated `mosquitto/config/passwords` or `mosquitto/config/acl` files.
Use the adapter ACL entries for reported state, intent results and entrance
health. Do not grant future hardware adapters broad write access unless a
specific commissioning exception is documented.

## G301 Adapter

The repository includes offline G301 Version G codecs, planning, readback
comparison and a simulator. The offline worker is slave-aware, asynchronous,
serialized per entrance, capability-aware and verifies actual status with
delayed retries. It is not a live service. Do not enable live G301 execution
until the project confirms:

- official entrance names and exact room membership
- gateway host/port and network route per entrance
- G301 slave address per room
- bench-tested read/write/readback behavior for one real device
- approved polling interval, timeout and retry policy

The live adapter must be deployed as a separate executable/container on the OT
network. Do not add it to the FastAPI lifespan. Run one serialized worker per
entrance and allow those independent entrance workers to execute concurrently.
Workers derive entrance membership from the registry and ignore disabled rooms.
The offline baseline uses one two-second operation attempt and a per-slave
exponential cooldown (five seconds initially, capped at five minutes), so one
offline indoor unit fails fast without repeatedly occupying the entrance bus.
Treat gateway loss separately because it is entrance-wide. A production queue
should release the bus lock during retry/readback delays and service other ready
slaves before revisiting a cooling-down device.

## Backups

Run a daily PostgreSQL backup and encrypt it where practical:

```bash
pg_dump "$DATABASE_URL" | gzip > "clock-ha-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
```

Test restore procedures before production go-live.

## Logs

Use structured JSON logs with:

- correlation ID
- Clock booking ID
- room key
- state transition
- retry count
- error classification

Configure log rotation in the host/container runtime.

## Recovery

- If Clock sync is stale, check Clock credentials, rate-limit errors and WAF/403 responses.
- If MQTT is down, outbox rows remain pending and are retried after broker recovery.
  Stale `publishing` rows are released by the outbox worker before claiming new
  rows.
- If Home Assistant restarts, publish MQTT Discovery again after receiving the HA birth/status topic.
- If room conflicts appear, suppress normal automation and resolve physical room allocation in Clock.
