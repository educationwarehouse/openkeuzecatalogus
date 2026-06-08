"""Consumer setup for scraper jobs."""

from pgqueuer.models import Job, Schedule
from pgskewer import ImprovedQueuer, parse_payload, unblock

from pgq.consumers.health import mark_heartbeat


def blocking_fn() -> str:
    """Block briefly and return a static value for testing."""
    import time

    time.sleep(1)
    return "something"


async def main() -> ImprovedQueuer:
    """Build and return the scraper queue with entrypoints registered."""
    pgq = await ImprovedQueuer.from_env()

    @pgq.entrypoint("dummy_scraper")
    async def dummy_scraper(job: Job) -> str:
        payload = parse_payload(job.payload)
        print("dummy processed message:", job.id, payload)

        return await unblock(blocking_fn)

    @pgq.schedule("healthcheck_every_minute_scrapers", "* * * * *")
    async def health_heartbeat(_: Schedule) -> None:
        mark_heartbeat()

    print("pgq ready:", pgq.channel)
    mark_heartbeat()
    return pgq
