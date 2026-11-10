"""Consumer setup for application logging jobs."""

from pgqueuer.models import Job
from pgskewer import unblock

from pgq.backend import pgq_backend
from pgq.queue import WorkerQueuer
from shared_code.services.applog.handler import process_applog_deque


def process_applog_deque_blocking() -> int:
    """Process queued applog signals inside the PGQ job's database context."""
    with pgq_backend("pgq.process_applog_deque") as backend:
        return process_applog_deque(db=backend.db)


def process_ticket_signal_queue_blocking() -> int:
    """Deliver queued error-ticket signals outside the original request context."""
    with pgq_backend("pgq.process_ticket_signal_queue") as backend:
        return backend.error_tickets.process_ticket_signal_queue()


async def main() -> WorkerQueuer:
    """Build and return the applog queue with entrypoints and health checks registered."""
    pgq = await WorkerQueuer.from_env()

    @pgq.entrypoint("process_applog_deque")
    async def process_applog_deque(_: Job) -> None:
        processed_count = await unblock(process_applog_deque_blocking)
        if processed_count:
            print(f"[applog] processed deque batch: {processed_count}")

    @pgq.entrypoint("process_ticket_signal_queue")
    async def process_ticket_signal_queue(_: Job) -> None:
        processed_count = await unblock(process_ticket_signal_queue_blocking)
        if processed_count:
            print(f"[error-signal] processed queue batch: {processed_count}")

    print("[pgq] ready:", pgq.channel)
    return pgq
