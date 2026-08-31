# Queue Processing (`pgq/`)

Background job processing runs as a separate Compose service built from `pgq/`, using PGQ (Postgres-backed queue) instead of a broker like Redis/RabbitMQ.

## Layout

- `pgq/Dockerfile`: builds on `educationwarehouse/edwhale-3.14`, installs `pgq/requirements.txt`, copies `heartbeat.sh`.
- `pgq/heartbeat.sh`: healthcheck script, fails unless `/tmp/pgq-heartbeat` was touched in the last 120 seconds. The consumer process is expected to touch this file on each poll cycle; see Compose healthcheck config for the `pgq` service.
- `pgq/consumers/`: one module per job family.
  - `applog.py`: `send_email_message` (mail delivery, see [Mail Integration](../integrations/mail.md)) and applog deque draining (see [Applog](../integrations/applog.md)).
  - `health.py`: health/heartbeat-related jobs.
  - `scrapers.py`: scraper import jobs (see [Scraper import architecture](scraper-imports.md)).
- `pgq/tests/`: consumer-level tests, run via `edwh test.go-pgq`.

## Queueing a Job Manually

- `edwh local.queue-pgq --entrypoint <entrypoint> --payload '{}'` enqueues a job directly for local testing (see [Tooling](../development/tooling.md)).

## Related Docs

- [Testing](../development/testing.md): `edwh test.go-pgq`, coverage report location.
- [Mail Integration](../integrations/mail.md), [Applog](../integrations/applog.md), [Scraper import architecture](scraper-imports.md): the actual job logic consumed here.
