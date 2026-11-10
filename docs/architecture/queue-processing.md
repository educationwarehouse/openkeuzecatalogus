# Queue Processing (`pgq/`)

Background job processing runs as a separate Compose service built from `pgq/`, using PGQ (Postgres-backed queue) instead of a broker like Redis/RabbitMQ.

## Layout

- `pgq/Dockerfile`: builds on `educationwarehouse/edwhale-3.14`, installs `pgq/requirements.txt`, copies `heartbeat.sh`.
- `pgq/pdf.Dockerfile`: extends the base worker image with WeasyPrint and its native rendering libraries for the PDF consumer.
- `pgq/heartbeat.sh`: healthcheck script, fails unless `/tmp/pgq-heartbeat` was touched in the last 120 seconds. Every worker and scheduler process updates its own file every 30 seconds while its manager runs and its event loop remains responsive. This checks process responsiveness; it does not prove that every job or database operation succeeds.
- `pgq/queue.py`: `WorkerQueuer` owns the local health heartbeat and wraps every worker entrypoint with a separate database ownership heartbeat, updated every 30 seconds independently of the job handler. Consumers do not need individual heartbeat decorators. Health updates do not use distributed cron tasks, which would only run in one replica at a time.
- `pgq/consumers/`: one module per job family.
  - `scheduler.py`: queues recurring work for the worker consumers. It is the only
    single-replica service that registers work-producing cron callbacks.
  - `applog.py`: applog deque draining and queued error-ticket signal delivery
    (see [Applog](../integrations/applog.md) and [Error signals](../integrations/error-signals.md)).
  - `health.py`: health/heartbeat-related jobs.
  - `maintenance.py`: `send_email_message` (mail delivery, see [Mail Integration](../integrations/mail.md)), materialized-view refreshes and abandoned-job cleanup. The scheduler queues cleanup each minute. Refresh runs are serialized with a database advisory semaphore. A populated view with a unique index is refreshed concurrently; other views are refreshed normally.
  - `pdf.py`: `render_vision_pdf` jobs. The worker reads staged keuzecanvas HTML and writes the rendered PDF and freshness marker on the shared storage volume.
  - `scrapers.py`: scraper import jobs and reconciliation of unfinished importer reports against failed queue results (see [Scraper import architecture](scraper-imports.md)). The scheduler queues reconciliation each minute, so history updates without a browser polling it.
- `pgq/tests/`: consumer-level tests, run via `edwh test.go-pgq`.

Jobs whose ownership heartbeat expires after five minutes are moved to terminal failure history, without automatic redelivery. `shared_code/services/deferred/job_health.py` handles only the queue records. PDF polling resolves the stored queue reference through `DeferredWork.result()`; scraper-owned reconciliation updates interrupted importer reports from those same persisted results. Work-producing cron callbacks belong to the scheduler. Process health is maintained locally, independently of the distributed schedule.

## PDF Consumer

`pgq-pdf` is built from `pgq/pdf.Dockerfile` and runs `pdf.py` with batch size `1`. It shares the
writable `./shared_user_storage` mount with `py4web`: the web tier stages a complete HTML document,
then queues only its gid and stores the job key beside the staged HTML, while the worker writes
the corresponding PDF. The job reference includes the staged content hash so unrelated failure
results do not affect a new request. Scale it independently with `PDF_WORKERS`, which defaults
to `2`. For the cache and retry behavior, see
[Storage integration](../integrations/storage.md#pdf-worker).

## Queueing a Job Manually

- `edwh local.queue-pgq --entrypoint <entrypoint> --payload '{}'` enqueues a job directly for local testing (see [Tooling](../development/tooling.md)).

## Related Docs

- [Testing](../development/testing.md): `edwh test.go-pgq`, coverage report location.
- [Mail Integration](../integrations/mail.md), [Applog](../integrations/applog.md), [Scraper import architecture](scraper-imports.md): the actual job logic consumed here.
