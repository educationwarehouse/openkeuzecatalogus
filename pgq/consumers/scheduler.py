"""Schedule recurring PGQ work without processing queued jobs."""

import uuid

from pgqueuer.models import Schedule
from pgskewer.helpers import queue_job_async

from pgq.backend import pgq_backend
from pgq.queue import WorkerQueuer


async def main() -> WorkerQueuer:
    """Build and return the scheduler with recurring work registered."""
    pgq = await WorkerQueuer.from_env()

    @pgq.schedule("import_kennisnet_catalogue_nightly", "0 3 * * *")
    async def import_kennisnet_catalogue_nightly(_: Schedule) -> None:
        """Queue one aggregate Kennisnet import each night."""
        job_key = str(uuid.uuid7())
        with pgq_backend("pgq.schedule_kennisnet_import") as backend:
            await queue_job_async(
                backend.db,
                "start_importer_edu-v-kennisnet",
                payload={"job_key": job_key, "trigger": "nightly"},
                dill=True,
                unique_key=job_key,
            )
        print(f"[scheduler] queued nightly Kennisnet import: {job_key}")

    @pgq.schedule("process_applog_deque_every_minute", "* * * * *")
    async def process_applog_deque_every_minute(_: Schedule) -> None:
        """Queue one applog deque-processing job each minute."""
        with pgq_backend("pgq.schedule_applog_deque") as backend:
            await queue_job_async(backend.db, "process_applog_deque", payload={}, dill=True)

    @pgq.schedule("process_ticket_signal_queue_every_minute", "* * * * *")
    async def process_ticket_signal_queue_every_minute(_: Schedule) -> None:
        """Queue one error-ticket signal processing job each minute."""
        with pgq_backend("pgq.schedule_ticket_signal_queue") as backend:
            await queue_job_async(backend.db, "process_ticket_signal_queue", payload={}, dill=True)

    @pgq.schedule("refresh_all_materialized_views_hourly", "0 * * * *")
    async def refresh_all_materialized_views_hourly(_: Schedule) -> None:
        """Queue one materialized-view refresh each hour."""
        with pgq_backend("pgq.schedule_materialized_view_refresh") as backend:
            await queue_job_async(backend.db, "refresh_all_materialized_views", payload={}, dill=True)

    @pgq.schedule("fail_abandoned_jobs_every_minute", "* * * * *")
    async def fail_abandoned_jobs_every_minute(_: Schedule) -> None:
        """Queue abandoned-worker cleanup through the single scheduler replica."""
        with pgq_backend("pgq.schedule_abandoned_job_cleanup") as backend:
            await queue_job_async(backend.db, "fail_abandoned_jobs", payload={}, dill=True)

    @pgq.schedule("reconcile_failed_importer_runs_every_minute", "* * * * *")
    async def reconcile_failed_importer_runs_every_minute(_: Schedule) -> None:
        """Queue importer-owned failure reconciliation on the existing scraper worker."""
        with pgq_backend("pgq.schedule_importer_run_reconciliation") as backend:
            await queue_job_async(backend.db, "reconcile_failed_importer_runs", payload={}, dill=True)

    print("[pgq] scheduler ready:", pgq.channel)
    return pgq
