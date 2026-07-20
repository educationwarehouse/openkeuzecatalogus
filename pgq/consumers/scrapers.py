"""Consumer setup for scraper jobs."""

from pgqueuer.models import Job, Schedule
from pgskewer import ImprovedQueuer, parse_payload, unblock

from pgq.consumers.health import mark_heartbeat
from shared_code.modules.scrapers.abs import ImportRunExtras
from shared_code.modules.scrapers.eduv import EduVImporter


async def main() -> ImprovedQueuer:
    """Build and return the scraper queue with entrypoints registered."""
    pgq = await ImprovedQueuer.from_env()

    @pgq.entrypoint("start_importer_edu-v")
    async def importer_eduv(job: Job) -> str:
        print(f"[importer] start 'edu-v' {job}")
        data = parse_payload(job.payload, strict=True, as_type=ImportRunExtras)
        print(f"[importer] {data}")
        data["sync_cdn"] = True

        result = await unblock(lambda: EduVImporter.run(**data))

        return str(result)

    @pgq.entrypoint("start_importer_none")
    async def importer_none(_: Job) -> str:
        print("[importer] start 'none'")
        return "-"

    @pgq.schedule("healthcheck_every_minute_scrapers", "* * * * *")
    async def health_heartbeat(_: Schedule) -> None:
        mark_heartbeat()

    print("pgq ready:", pgq.channel)
    mark_heartbeat()
    return pgq
