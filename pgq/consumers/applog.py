"""Consumer setup for application logging jobs."""

import datetime as dt

from pgqueuer.models import Job, Schedule
from pgskewer import ImprovedQueuer, parse_payload, unblock

from pgq.backend import pgq_backend
from pgq.consumers.health import mark_heartbeat
from shared_code.services.applog.handler import process_applog_deque
from shared_code.services.mail.contracts import QueuedEmail


def send_email_message_blocking(data: QueuedEmail) -> None:
    """Send an email payload using the configured mailer inside a DB context."""
    with pgq_backend("pgq.send_email_message") as backend:
        backend.mailer.send_email_message(**data)


def refresh_catalog_search_report_blocking() -> None:
    """Refresh the catalog-search reporting view."""
    with pgq_backend("pgq.refresh_catalog_search_report") as backend:
        backend.applog.refresh_catalog_search_report()


def process_applog_deque_blocking() -> int:
    """Process queued applog signals inside the PGQ job's database context."""
    with pgq_backend("pgq.process_applog_deque") as backend:
        return process_applog_deque(db=backend.db)


async def main() -> ImprovedQueuer:
    """Build and return the applog queue with schedules registered."""
    pgq = await ImprovedQueuer.from_env()

    @pgq.entrypoint("send_email_message")
    async def send_email_message(job: Job) -> None:
        # todo: move to different pgq container once we have more util tasks
        data = parse_payload(job.payload, strict=True, as_type=QueuedEmail)

        return await unblock(lambda: send_email_message_blocking(data))

    @pgq.schedule("process_applog_deque_every_minute", "* * * * *")
    async def process_applog_deque_every_minute(_: Schedule) -> None:
        processed_count = await unblock(process_applog_deque_blocking)
        if processed_count:
            print(f"Processed applog deque batch: {processed_count}")

    @pgq.schedule("refresh_catalog_search_report_nightly", "47 2 * * *")
    async def refresh_catalog_search_report_nightly(_: Schedule) -> None:
        await unblock(refresh_catalog_search_report_blocking)

    @pgq.schedule("healthcheck_every_minute_applog", "* * * * *")
    async def healthcheck_every_minute(_: Schedule) -> None:
        mark_heartbeat()
        print(f"[health] Ran at {dt.datetime.now():%H:%M:%S}")

    print("pgq ready:", pgq.channel)
    mark_heartbeat()
    return pgq
