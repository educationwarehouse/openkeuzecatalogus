"""Consumer setup for scraper jobs."""

from pgqueuer.models import Job
from pgskewer import parse_payload, unblock

from pgq.backend import pgq_backend
from pgq.queue import WorkerQueuer
from shared_code.modules.scrapers.abs import ImportRunExtras
from shared_code.modules.scrapers.eduv import EduVImporter
from shared_code.modules.scrapers.kennisnet_catalogue import (
    KennisnetCatalogueRefreshRequest,
    refresh_kennisnet_catalogue_if_stale,
)
from shared_code.modules.scrapers.kennisnet_import import KennisnetCatalogueImporter
from shared_code.modules.scrapers.run_log import reconcile_failed_importer_runs


def reconcile_failed_importer_runs_blocking() -> int:
    """Update importer history independently of whether anyone polls its status."""
    with pgq_backend("pgq.reconcile_failed_importer_runs") as backend:
        reconciled = reconcile_failed_importer_runs(backend.db)
        if reconciled:
            print(f"[importer] reconciled {reconciled} failed runs")
        return reconciled


async def run_kennisnet_import(job: Job) -> str:
    """Import Kennisnet from one entrypoint without nesting cancellation scopes.

    Each alias needs its own entrypoint function. Stacking pgskewer
    entrypoint decorators re-enters the job's AnyIO cancellation scope.
    """
    data = parse_payload(job.payload, strict=True, as_type=ImportRunExtras)
    result = await unblock(lambda: KennisnetCatalogueImporter.run(**data))
    return str(result)


def register_kennisnet_importers(pgq: WorkerQueuer) -> None:
    """Register each Kennisnet alias with its own entrypoint function."""

    @pgq.entrypoint("start_importer_edu-v-kennisnet")
    async def importer_kennisnet(job: Job) -> str:
        return await run_kennisnet_import(job)

    @pgq.entrypoint("start_importer_edu-v-kennisnet-v1")
    async def importer_kennisnet_v1(job: Job) -> str:
        return await run_kennisnet_import(job)

    @pgq.entrypoint("start_importer_edu-v-kennisnet-v2")
    async def importer_kennisnet_v2(job: Job) -> str:
        return await run_kennisnet_import(job)


async def main() -> WorkerQueuer:
    """Build and return the scraper queue with entrypoints registered."""
    pgq = await WorkerQueuer.from_env()

    @pgq.entrypoint("reconcile_failed_importer_runs")
    async def reconcile_failed_imports(_: Job) -> None:
        await unblock(reconcile_failed_importer_runs_blocking)

    @pgq.entrypoint("start_importer_edu-v")
    async def importer_eduv(job: Job) -> str:
        print(f"[importer] start 'edu-v' {job}")
        data = parse_payload(job.payload, strict=True, as_type=ImportRunExtras)
        print(f"[importer] {data}")

        result = await unblock(lambda: EduVImporter.run(**data))

        return str(result)

    @pgq.entrypoint("start_importer_none")
    async def importer_none(_: Job) -> str:
        print("[importer] start 'none'")
        return "-"

    register_kennisnet_importers(pgq)

    @pgq.entrypoint("refresh_kennisnet_catalogue")
    async def refresh_kennisnet_catalogue(job: Job) -> None:
        data = parse_payload(job.payload, strict=True, as_type=KennisnetCatalogueRefreshRequest)
        await unblock(lambda: refresh_kennisnet_catalogue_if_stale(**data))

    print("pgq ready:", pgq.channel)
    return pgq
