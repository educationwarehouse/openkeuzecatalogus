"""Consumer setup for utility jobs and scheduled database maintenance."""

import datetime as dt

from pgqueuer.models import Job, Schedule
from pgskewer import ImprovedQueuer, parse_payload, unblock

from pgq.backend import pgq_backend
from pgq.consumers.health import mark_heartbeat
from shared_code.infra.database.materialized_views import refresh_all_materialized_views
from shared_code.services.mail.contracts import QueuedEmail


def send_email_message_blocking(data: QueuedEmail) -> None:
    """Send an email payload using the configured mailer inside a DB context."""
    with pgq_backend("pgq.send_email_message") as backend:
        backend.mailer.send_email_message(**data)


def refresh_all_materialized_views_blocking() -> list[str]:
    """Refresh materialized views within a dedicated PGQ database context."""
    with pgq_backend("pgq.refresh_all_materialized_views") as backend:
        return refresh_all_materialized_views(backend.db)


async def main() -> ImprovedQueuer:
    """Build and return the utility queue with entrypoints and schedules registered."""
    pgq = await ImprovedQueuer.from_env()

    @pgq.entrypoint("send_email_message")
    async def send_email_message(job: Job) -> None:
        data = parse_payload(job.payload, strict=True, as_type=QueuedEmail)
        await unblock(lambda: send_email_message_blocking(data))

    @pgq.schedule("refresh_all_materialized_views_hourly", "0 * * * *")
    async def refresh_all_materialized_views_hourly(_: Schedule) -> None:
        refreshed_views = await unblock(refresh_all_materialized_views_blocking)
        print(f"[maintenance] refreshed materialized views: {', '.join(refreshed_views) or 'none'}")

    @pgq.schedule("healthcheck_every_minute_maintenance", "* * * * *")
    async def healthcheck_every_minute(_: Schedule) -> None:
        mark_heartbeat()
        print(f"[health] Ran at {dt.datetime.now():%H:%M:%S}")

    print("[pgq] ready:", pgq.channel)
    mark_heartbeat()
    return pgq
