"""Engine-neutral contract for HTML-to-PDF rendering, plus the shared handover helpers."""

import abc
import base64
import hashlib
import json
import logging
import os
import pathlib
import re
import tempfile
import time
import typing as t
import uuid
from concurrent.futures import Executor, ThreadPoolExecutor
from urllib.parse import quote, unquote

from endow import Service
from filelock import FileLock

from shared_code.services.deferred import DeferredJob
from shared_code.services.images import ImageStorage, ImageStorageError
from shared_code.util.lists import uniq

_STAGED_IMAGE_URL = re.compile(r"image-storage://(?P<url>[^\"'\s>]+)")
logger = logging.getLogger(__name__)
PDF_WAIT_TIMEOUT = 600


class PdfRenderRequest(t.TypedDict):
    """The engine-neutral input for one HTML-to-PDF render.

    `html` is a finished document: the service never templates. The PDF worker replaces its
    storage-image markers with data URLs, so stylesheet and image paths do not need to resolve
    across the web and worker containers.
    """

    html: str
    css: t.NotRequired[str]


class VisionPdfJob(t.TypedDict):
    """Deferred-job payload for one keuzecanvas PDF render.

    Only the gid travels through the queue; the HTML is staged on the shared volume, so payloads
    stay small no matter how many cover images the document embeds.
    """

    gid: str


class PdfUnavailableError(RuntimeError):
    """Raised when a PDF service cannot render, usually a broken or absent engine install."""


class PdfService(Service, abc.ABC):
    """Abstract HTML-to-PDF contract plus the shared staging and caching helpers.

    Split deliberately. Everything except `render` is path and hash bookkeeping that the *web*
    tier needs, to stage a document and to skip one that has not changed; `render` is the only
    member that needs a rendering engine, and it runs in the `pgq-pdf` worker. That is why both
    tiers can declare this service even though only one of them can call `render`.

    Moving these documents to object storage (the old app's `# todo: opslaan op b2?`) is a change
    to this class alone.
    """

    image_storage: ImageStorage

    @property
    def storage_root(self) -> pathlib.Path:
        """Return the directory holding staged HTML and rendered PDFs."""
        base = os.environ.get("SHARED_USER_STORAGE", "/shared_user_storage").strip()
        return pathlib.Path(base or "/shared_user_storage") / "keuzecanvas"

    def html_path(self, gid: str) -> pathlib.Path:
        """Return the path of the staged HTML for one document."""
        return self.storage_root / f"{gid}.html"

    def pdf_path(self, gid: str) -> pathlib.Path:
        """Return the path of the rendered PDF for one document."""
        return self.storage_root / f"{gid}.pdf"

    def hash_path(self, gid: str) -> pathlib.Path:
        """Return the path of the freshness marker for one document."""
        return self.storage_root / f"{gid}.hash"

    def failure_path(self, gid: str) -> pathlib.Path:
        """Return the marker for an unsuccessful render of staged HTML."""
        return self.storage_root / f"{gid}.failed"

    def job_path(self, gid: str) -> pathlib.Path:
        """Return the queue reference for the currently staged PDF request."""
        return self.storage_root / f"{gid}.job"

    def record_job(self, gid: str, job: DeferredJob, html: str) -> None:
        """Associate a queued render with the staged document it belongs to."""
        metadata = {
            "key": str(job.key),
            "entrypoint": job.entrypoint,
            "content_hash": self.content_hash(html),
        }
        self._write_atomic(self.job_path(gid), json.dumps(metadata).encode("utf-8"))

    def staged_job(self, gid: str, html: str) -> DeferredJob | None:
        """Recover the queue reference only when it belongs to the staged content."""
        path = self.job_path(gid)
        if not path.exists():
            return None
        metadata = json.loads(path.read_text(encoding="utf-8"))
        if metadata["content_hash"] != self.content_hash(html):
            return None
        return DeferredJob(key=uuid.UUID(metadata["key"]), entrypoint=metadata["entrypoint"])

    def mark_failed(self, gid: str, html: str) -> None:
        """Expose a failed render to status polling without storing exception details."""
        self._write_atomic(self.failure_path(gid), self.content_hash(html).encode("ascii"))

    def mark_staged_request_failed(self, gid: str) -> None:
        """Record a failed worker or subprocess for the staged document, if present."""
        if not self.html_path(gid).exists():
            return
        self.mark_failed(gid, self.load_request(gid)["html"])

    def has_failed(self, gid: str, html: str) -> bool:
        """Only report failures belonging to the currently staged document."""
        marker = self.failure_path(gid)
        return marker.exists() and marker.read_text() == self.content_hash(html)

    def has_timed_out(self, gid: str) -> bool:
        """Stop waiting indefinitely when a worker never produces a result."""
        return time.time() - self.html_path(gid).stat().st_mtime >= PDF_WAIT_TIMEOUT

    def content_hash(self, html: str) -> str:
        """Hash the HTML that a PDF was produced from."""
        return hashlib.sha256(html.encode("utf-8")).hexdigest()

    @staticmethod
    def inline_image(content: bytes, content_type: str) -> str:
        """Encode an image as a data URL for a staged HTML document."""
        media_type = content_type.split(";", 1)[0].strip().lower()
        if not media_type.startswith("image/"):
            raise ValueError(f"Expected an image content type, got {content_type!r}")

        encoded_content = base64.b64encode(content).decode("ascii")
        return f"data:{media_type};base64,{encoded_content}"

    @staticmethod
    def staged_image_url(url: str) -> str:
        """Mark a storage URL for deferred inlining by the PDF worker."""
        return f"image-storage://{quote(url, safe='')}"

    def supports_image(self, url: str) -> bool:
        """Recognise images owned by the configured image storage."""
        return self.image_storage.is_file_url(url)

    def inline_staged_images(self, request: PdfRenderRequest) -> PdfRenderRequest:
        """Embed each allowed cover once, with bounded concurrent downloads."""
        urls = uniq(unquote(match["url"]) for match in _STAGED_IMAGE_URL.finditer(request["html"]))
        images = self.download_staged_images(urls)
        request["html"] = _STAGED_IMAGE_URL.sub(lambda match: images[unquote(match["url"])], request["html"])
        return request

    def download_staged_images(self, urls: list[str]) -> dict[str, str]:
        """Download staged images concurrently; subclasses may replace the strategy."""
        with self.image_download_executor() as executor:
            return dict(zip(urls, executor.map(self.read_staged_image, urls), strict=True))

    def image_download_executor(self) -> Executor:
        """Create the executor used for one batch of staged image downloads."""
        return ThreadPoolExecutor(max_workers=4)

    def read_staged_image(self, url: str) -> str:
        """Inline one storage image, leaving an empty image when it is unavailable."""
        try:
            content, content_type = self.image_storage.download_url(url)
            return self.inline_image(content, content_type)
        except (ImageStorageError, ValueError) as error:
            logger.warning("PDF cover download failed for %s: %s", url, error)
            return "data:,"

    def is_fresh(self, gid: str, html: str) -> bool:
        """Return whether a PDF for exactly this HTML already exists.

        The marker is written only after a successful render, so a failed or crashed job leaves
        the document looking absent and the next request re-enqueues it.
        """
        marker = self.hash_path(gid)
        if not (self.pdf_path(gid).exists() and marker.exists()):
            return False

        return marker.read_text().strip() == self.content_hash(html)

    def build_request(self, gid: str, html: str, css: str = "") -> VisionPdfJob:
        """Stage one document for rendering and return the payload to enqueue."""
        target = self.html_path(gid)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.failure_path(gid).unlink(missing_ok=True)
        self.job_path(gid).unlink(missing_ok=True)
        self._write_atomic(target, (self._embed_css(html, css) if css else html).encode("utf-8"))
        return VisionPdfJob(gid=gid)

    def render_lock(self, gid: str) -> FileLock:
        """Return a cross-process lock for one PDF document."""
        self.storage_root.mkdir(parents=True, exist_ok=True)
        return FileLock(self.storage_root / f"{gid}.lock")

    @staticmethod
    def _write_atomic(target: pathlib.Path, content: bytes) -> None:
        """Publish complete files so readers never see a partially written export."""
        with tempfile.TemporaryDirectory(dir=target.parent) as directory:
            temporary = pathlib.Path(directory) / target.name
            temporary.write_bytes(content)
            temporary.replace(target)

    def load_request(self, gid: str) -> PdfRenderRequest:
        """Read back a staged document, for the worker that converts it."""
        staged = self.html_path(gid)
        if not staged.exists():
            raise PdfUnavailableError(f"No staged HTML for {gid}: never built, or already cleaned up.")

        return PdfRenderRequest(html=staged.read_text(encoding="utf-8"))

    def store(self, gid: str, pdf: bytes, request: PdfRenderRequest | None = None) -> str:
        """Persist rendered bytes and mark them fresh for the HTML that was rendered."""
        target = self.pdf_path(gid)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._write_atomic(target, pdf)
        # written after the PDF, so an interrupted write never looks fresh
        html = request["html"] if request else self.load_request(gid)["html"]
        self._write_atomic(self.hash_path(gid), self.content_hash(html).encode("ascii"))
        self.failure_path(gid).unlink(missing_ok=True)
        return str(target)

    @staticmethod
    def _embed_css(html: str, css: str) -> str:
        """Inline a stylesheet into a staged document."""
        style = f"<style>{css}</style>"
        if "</head>" in html:
            return html.replace("</head>", f"{style}</head>", 1)

        return f"{style}{html}"

    @abc.abstractmethod
    def render(self, request: PdfRenderRequest) -> bytes:
        """Convert one staged document to PDF bytes, or raise `PdfUnavailableError`.

        Only callable where a rendering engine is installed, which is the `pgq-pdf` worker.
        """
        ...

    @classmethod
    def from_env(cls) -> PdfService:
        """Build the configured PDF implementation, WeasyPrint by default."""
        engine = os.environ.get("PDF_ENGINE", "weasyprint").strip().lower()
        if engine in {"", "weasyprint"}:
            from .weasyprint import WeasyPrintPdfService

            return WeasyPrintPdfService.from_env()
        else:
            raise ValueError(f"Unsupported PDF_ENGINE: {engine}")
