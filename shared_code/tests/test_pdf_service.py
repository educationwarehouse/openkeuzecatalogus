"""Tests for the engine-neutral PDF handover helpers."""

import pathlib
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from shared_code.services.images import MockImageStorage
from shared_code.services.pdf.contracts import PdfRenderRequest, PdfService, PdfUnavailableError


class SingleWorkerPdfService(PdfService):
    """Exercise image hooks through the public staging API with a real executor."""

    @classmethod
    def from_env(cls) -> SingleWorkerPdfService:
        return cls()

    def image_download_executor(self) -> ThreadPoolExecutor:
        return ThreadPoolExecutor(max_workers=1, thread_name_prefix="pdf-image-test")

    def read_staged_image(self, url: str) -> str:
        assert threading.current_thread().name.startswith("pdf-image-test")
        return super().read_staged_image(url)

    def render(self, request: PdfRenderRequest) -> bytes:
        raise NotImplementedError("This test service only stages images")


@pytest.fixture()
def pdf_service(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> PdfService:
    """Return a PDF service wired through Endow and rooted in the test directory."""
    monkeypatch.setenv("SHARED_USER_STORAGE", str(tmp_path))
    return PdfService.with_injected(image_storage=MockImageStorage(tmp_path / "images"))


def test_embed_css_injects_before_head(pdf_service: PdfService) -> None:
    """CSS is embedded at the document head when one exists."""
    assert pdf_service._embed_css("<html><head></head><body></body></html>", "body{}") == (
        "<html><head><style>body{}</style></head><body></body></html>"
    )


def test_embed_css_prepends_when_no_head(pdf_service: PdfService) -> None:
    """CSS is prepended when the document has no head tag."""
    assert pdf_service._embed_css("<html><body></body></html>", "body{}") == (
        "<style>body{}</style><html><body></body></html>"
    )


def test_paths_and_content_hash_are_stable(pdf_service: PdfService) -> None:
    """Document, PDF, and marker paths live below the service root."""
    assert pdf_service.html_path("abc") == pdf_service.storage_root / "abc.html"
    assert pdf_service.pdf_path("abc") == pdf_service.storage_root / "abc.pdf"
    assert pdf_service.hash_path("abc") == pdf_service.storage_root / "abc.hash"
    assert pdf_service.content_hash("<html></html>") == pdf_service.content_hash("<html></html>")
    assert pdf_service.content_hash("<html></html>") != pdf_service.content_hash("<html>x</html>")


def test_build_load_store_round_trip(pdf_service: PdfService) -> None:
    """A staged document can be loaded, rendered, and marked fresh."""
    html = "<html><head></head><body>visie</body></html>"
    css = "body { color: black; }"

    payload = pdf_service.build_request("doc", html, css=css)
    assert payload == {"gid": "doc"}

    request = pdf_service.load_request("doc")
    assert "<style>body { color: black; }</style>" in request["html"]
    assert not pdf_service.is_fresh("doc", request["html"])

    assert pdf_service.store("doc", b"PDF") == str(pdf_service.pdf_path("doc"))
    assert pdf_service.pdf_path("doc").read_bytes() == b"PDF"
    assert pdf_service.is_fresh("doc", request["html"])
    assert not pdf_service.is_fresh("doc", request["html"] + "changed")


def test_inline_staged_images_downloads_only_storage_urls(pdf_service: PdfService) -> None:
    """The PDF worker resolves its storage marker to an image data URL."""
    _, image_url = pdf_service.image_storage.upload_bytes("cover.jpg", b"cover", "image/jpeg")
    request = {"html": f'<img src="{pdf_service.staged_image_url(image_url)}" />'}

    assert pdf_service.inline_staged_images(request) is request
    assert request["html"] == '<img src="data:image/jpeg;base64,Y292ZXI=" />'


def test_inline_staged_images_rejects_non_storage_urls(pdf_service: PdfService) -> None:
    """A staged URL outside image storage is not downloaded by the PDF worker."""
    request = {"html": f'<img src="{pdf_service.staged_image_url("https://example.test/cover.jpg")}" />'}

    pdf_service.inline_staged_images(request)

    assert request["html"] == '<img src="data:," />'


def test_staged_images_use_subclass_download_hooks(tmp_path: pathlib.Path) -> None:
    """A subclass controls the executor and image reader without replacing staging."""
    storage = MockImageStorage(tmp_path / "images")
    service = SingleWorkerPdfService.with_injected(image_storage=storage)
    assert isinstance(service, SingleWorkerPdfService)
    _, image_url = storage.upload_bytes("cover.jpg", b"cover", "image/jpeg")
    image = f'<img src="{service.staged_image_url(image_url)}" />'
    request = PdfRenderRequest(html=image + image)

    service.inline_staged_images(request)

    assert request["html"] == '<img src="data:image/jpeg;base64,Y292ZXI=" />' * 2


def test_load_request_raises_when_no_html_is_staged(pdf_service: PdfService) -> None:
    """Missing staged HTML is a service failure, not a file-not-found leak."""
    with pytest.raises(PdfUnavailableError, match="No staged HTML"):
        pdf_service.load_request("missing")


def test_pdf_render_lock_serialises_duplicate_exports(pdf_service: PdfService) -> None:
    """A second worker waits and reuses the document completed by the first."""
    started = threading.Event()
    entered = threading.Event()
    pdf_service.build_request("document", "<p>Vision</p>")

    def waiting_worker() -> bool:
        started.set()
        with pdf_service.render_lock("document"):
            entered.set()
            return pdf_service.is_fresh("document", "<p>Vision</p>")

    with ThreadPoolExecutor(max_workers=1) as pool:
        with pdf_service.render_lock("document"):
            waiting = pool.submit(waiting_worker)
            assert started.wait(timeout=2)
            assert not entered.wait(timeout=0.1)
            pdf_service.store("document", b"PDF")
        assert waiting.result(timeout=2)


def test_failed_pdf_can_be_retried_without_a_stale_error(pdf_service: PdfService) -> None:
    """Polling can distinguish failure, retry and a successful replacement."""
    html = "<p>Vision</p>"
    pdf_service.build_request("document", html)
    pdf_service.mark_failed("document", html)
    assert pdf_service.has_failed("document", html)
    assert not pdf_service.has_failed("document", "<p>Updated vision</p>")
    pdf_service.build_request("document", html)
    assert not pdf_service.has_failed("document", html)
    pdf_service.store("document", b"PDF")
    assert pdf_service.is_fresh("document", html)
