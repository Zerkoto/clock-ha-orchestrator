# Operations Runbook

## Time

- Store application timestamps in UTC.
- Evaluate hotel policy in `Europe/Sofia`.
- Keep host and containers synchronized with NTP.

## Secrets

- Use environment variables or a secrets manager.
- Do not commit production `.env` files.
- Never log Clock API secrets, authorization headers, payment data or guest PII.

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

