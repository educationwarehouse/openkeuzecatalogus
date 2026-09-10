"""Consumer setup for application logging jobs."""

import datetime as dt

from pgqueuer.models import Schedule
from pgskewer import ImprovedQueuer, unblock

from pgq.backend import pgq_backend
from pgq.consumers.health import mark_heartbeat
from shared_code.services.applog.handler import process_applog_deque


def process_applog_deque_blocking() -> int:
    """Process queued applog signals inside the PGQ job's database context."""
    with pgq_backend("pgq.process_applog_deque") as backend:
        return process_applog_deque(db=backend.db)


def process_ticket_signal_queue_blocking() -> int:
    """Deliver queued error-ticket signals outside the original request context."""
    with pgq_backend("pgq.process_ticket_signal_queue") as backend:
        return backend.error_tickets.process_ticket_signal_queue()


async def main() -> ImprovedQueuer:
    """Build and return the applog queue with schedules registered."""
    pgq = await ImprovedQueuer.from_env()

    @pgq.schedule("process_applog_deque_every_minute", "* * * * *")
    async def process_applog_deque_every_minute(_: Schedule) -> None:
        processed_count = await unblock(process_applog_deque_blocking)
        if processed_count:
            print(f"[applog] processed deque batch: {processed_count}")

    @pgq.schedule("process_ticket_signal_queue_every_minute", "* * * * *")
    async def process_ticket_signal_queue_every_minute(_: Schedule) -> None:
        processed_count = await unblock(process_ticket_signal_queue_blocking)
        if processed_count:
            print(f"[error-signal] processed queue batch: {processed_count}")

    @pgq.schedule("healthcheck_every_minute_applog", "* * * * *")
    async def healthcheck_every_minute(_: Schedule) -> None:
        mark_heartbeat()
        print(f"[health] Ran at {dt.datetime.now():%H:%M:%S}")

    print("[pgq] ready:", pgq.channel)
    mark_heartbeat()
    return pgq
