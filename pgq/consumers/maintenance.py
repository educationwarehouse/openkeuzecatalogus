"""Consumer setup for utility jobs and scheduled database maintenance."""

import time

from pgqueuer.models import Job
from pgskewer import parse_payload, unblock

from pgq.backend import pgq_backend
from pgq.queue import WorkerQueuer
from shared_code.data_model import AnyDict
from shared_code.infra.database.materialized_views import refresh_all_materialized_views
from shared_code.modules.decision_processes.ai import VisionEnhancementResponse
from shared_code.services.deferred.job_health import fail_abandoned_jobs
from shared_code.services.llm import CompletionRequest
from shared_code.services.mail.contracts import QueuedEmail


def send_email_message_blocking(data: QueuedEmail) -> None:
    """Send an email payload using the configured mailer inside a DB context."""
    with pgq_backend("pgq.send_email_message") as backend:
        backend.mailer.send_email_message(**data)


def refresh_all_materialized_views_blocking() -> list[str]:
    """Refresh materialized views within a dedicated PGQ database context."""
    with pgq_backend("pgq.refresh_all_materialized_views") as backend:
        return refresh_all_materialized_views(backend.db)


def enhance_vision_blocking(request: CompletionRequest) -> str:
    """Generate one structured vision enhancement in a dedicated DB context."""
    with pgq_backend("pgq.enhance_vision") as backend:
        return backend.llm.complete_structured(request, VisionEnhancementResponse).improved_vision


def compare_vision_blocking(request: CompletionRequest) -> AnyDict:
    """Generate a playground result with provider duration, excluding queue time."""
    started = time.monotonic()
    text = enhance_vision_blocking(request)
    return {"text": text, "duration_seconds": round(time.monotonic() - started, 2)}


def fail_abandoned_jobs_blocking() -> int:
    """Record terminal queue failures for jobs whose workers disappeared."""
    with pgq_backend("pgq.fail_abandoned_jobs") as backend:
        return fail_abandoned_jobs(backend.db)


async def main() -> WorkerQueuer:
    """Build and return the utility queue with entrypoints and health checks registered."""
    pgq = await WorkerQueuer.from_env()

    @pgq.entrypoint("send_email_message")
    async def send_email_message(job: Job) -> None:
        data = parse_payload(job.payload, strict=True, as_type=QueuedEmail)
        await unblock(lambda: send_email_message_blocking(data))

    @pgq.entrypoint("enhance_vision")
    async def enhance_vision(job: Job) -> str:
        request = parse_payload(job.payload, strict=True, as_type=CompletionRequest)
        return await unblock(lambda: enhance_vision_blocking(request))

    @pgq.entrypoint("compare_vision")
    async def compare_vision(job: Job) -> AnyDict:
        request = parse_payload(job.payload, strict=True, as_type=CompletionRequest)
        return await unblock(lambda: compare_vision_blocking(request))

    @pgq.entrypoint("refresh_all_materialized_views")
    async def refresh_all_materialized_views(_: Job) -> None:
        refreshed_views = await unblock(refresh_all_materialized_views_blocking)
        print(f"[maintenance] refreshed materialized views: {', '.join(refreshed_views) or 'none'}")

    @pgq.entrypoint("fail_abandoned_jobs")
    async def fail_abandoned(_: Job) -> None:
        failed = await unblock(fail_abandoned_jobs_blocking)
        if failed:
            print(f"[maintenance] Failed {failed} abandoned jobs")

    print("[pgq] ready:", pgq.channel)
    return pgq
