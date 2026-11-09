"""Consumer setup for keuzecanvas PDF rendering.

Runs only in the `pgq-pdf` image, which is the one place WeasyPrint's native libraries are
installed. The web tier stages the HTML on the shared volume and enqueues a gid; this worker
converts it and writes the PDF beside it.
"""

from pgqueuer.models import Job
from pgskewer import parse_payload, unblock

from pgq.backend import pgq_backend
from pgq.queue import WorkerQueuer
from shared_code.services.pdf import VisionPdfJob


def render_vision_pdf_blocking(data: VisionPdfJob) -> str:
    """Convert one staged keuzecanvas document and return the stored PDF path.

    Rendering itself needs no database, but the job runs inside `pgq_backend` like every other
    consumer so that applog and error-ticket reporting behave the same way here.
    """
    with pgq_backend("pgq.render_vision_pdf") as backend:
        gid = data["gid"]
        with backend.pdf.render_lock(gid):
            pdf_request = backend.pdf.load_request(gid)
            if backend.pdf.is_fresh(gid, pdf_request["html"]):
                return str(backend.pdf.pdf_path(gid))
            try:
                render_request = backend.pdf.inline_staged_images(pdf_request.copy())
                rendered = backend.pdf.render(render_request)
                return backend.pdf.store(gid, rendered, request=pdf_request)
            except Exception:
                backend.pdf.mark_failed(gid, pdf_request["html"])
                raise


async def main() -> WorkerQueuer:
    """Build and return the PDF queue with its entrypoint registered."""
    pgq = await WorkerQueuer.from_env()

    @pgq.entrypoint("render_vision_pdf", concurrency_limit=1)
    async def render_vision_pdf(job: Job) -> str:
        data = parse_payload(job.payload, strict=True, as_type=VisionPdfJob)
        try:
            return await unblock(lambda: render_vision_pdf_blocking(data))
        except Exception:
            # A killed rendering subprocess cannot write its own failure marker.
            with pgq_backend("pgq.render_vision_pdf.failed") as backend:
                backend.pdf.mark_staged_request_failed(data["gid"])
            raise

    print("[pgq] ready:", pgq.channel)
    return pgq
