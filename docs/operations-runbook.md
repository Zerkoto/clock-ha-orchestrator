# Operations Runbook

## Time

- Store application timestamps in UTC.
- Evaluate hotel policy in `Europe/Sofia`.
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
- If Home Assistant restarts, publish MQTT Discovery again after receiving the HA birth/status topic.
- If room conflicts appear, suppress normal automation and resolve physical room allocation in Clock.
