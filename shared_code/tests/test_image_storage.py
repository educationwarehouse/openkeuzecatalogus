"""Tests for the local image-storage implementation."""

import hashlib
import typing as t
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import quote

import pytest

from shared_code.services.images import ImageDownloadError, ImageStorage, MinioImageStorage, MockImageStorage

if t.TYPE_CHECKING:
    from pytest import MonkeyPatch


@contextmanager
def external_image_server() -> t.Iterator[str]:
    """Serve deterministic HTTP image responses without contacting external services."""

    class ImageHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/missing.png":
                self.send_error(404)
                return

            self.send_response(200)
            if self.path == "/cover.jpg":
                self.send_header("Content-Type", "image/jpeg; charset=binary")
            self.end_headers()
            self.wfile.write(b"image-bytes")

        def log_message(self, format: str, *args: t.Any) -> None:
            """Keep the test output free of expected HTTP request logs."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), ImageHandler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_create_filename_hashes_isbn_and_sanitizes_original_filename(monkeypatch: MonkeyPatch) -> None:
    """Image filenames should be deterministic, salted, and safe for object storage."""
    monkeypatch.setenv("IMAGE_STORAGE_HASH_SALT", "test-salt")

    filename = ImageStorage.create_filename("9789402054958", "../../Cover Café.JPG")

    expected_prefix = hashlib.sha1(b"test-salt_9789402054958").hexdigest()
    assert filename == f"{expected_prefix}_cover-cafe.jpg"


def test_mock_image_storage_persists_bytes_and_returns_file_url(tmp_path: Path) -> None:
    """The local mock should retain bytes and serve a short file:// URL."""
    storage = MockImageStorage(tmp_path)

    filename, url = storage.upload_bytes("cover.png", b"image-bytes", content_type="image/png")

    assert filename == "cover.png"
    assert (tmp_path / "cover.png").read_bytes() == b"image-bytes"
    assert url == f"file://{quote(str(tmp_path / 'cover.png'))}"
    assert storage.get_file_url(filename) == url
    assert storage.is_file_url(url) is True
    assert storage.is_file_url("https://images.example.test/cover.png") is False


def test_mock_image_storage_imports_and_downloads_a_local_file(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """Local file URLs can be imported without making an HTTP request."""
    monkeypatch.setenv("IMAGE_STORAGE_HASH_SALT", "test-salt")
    source = tmp_path / "source cover.png"
    source.write_bytes(b"image-bytes")
    storage = MockImageStorage(tmp_path / "storage")

    filename, url = storage.upload_from_url("9789402054958", source.as_uri())

    assert filename.endswith("_source-cover.png")
    assert storage.download_url(url) == (b"image-bytes", "image/png")


def test_mock_image_storage_rejects_invalid_local_paths_and_urls(tmp_path: Path) -> None:
    """The local backend confines filenames and only reads its own URLs."""
    storage = MockImageStorage(tmp_path)

    with pytest.raises(ValueError, match="must not contain a path"):
        storage.upload_bytes("nested/cover.png", b"image-bytes")

    with pytest.raises(ImageDownloadError, match="not served"):
        storage.download_url("file:///outside/cover.png")

    with pytest.raises(ImageDownloadError, match="Unable to download"):
        storage.upload_from_url("isbn", "file://example.test/cover.png")


def test_image_storage_downloads_external_images_and_normalises_content_type(tmp_path: Path) -> None:
    """External downloads retain bytes and remove Content-Type parameters."""
    storage = MockImageStorage(tmp_path)

    with external_image_server() as server_url:
        content, content_type = storage.download_external_url(f"{server_url}/cover.jpg")

    assert content == b"image-bytes"
    assert content_type == "image/jpeg"


def test_image_storage_external_download_uses_filename_type_and_rejects_failed_urls(tmp_path: Path) -> None:
    """External downloads fall back to the filename type and expose request failures."""
    storage = MockImageStorage(tmp_path)

    with external_image_server() as server_url:
        assert storage.download_external_url(f"{server_url}/cover.png") == (b"image-bytes", "image/png")
        with pytest.raises(ImageDownloadError, match="Unable to download"):
            storage.download_external_url(f"{server_url}/missing.png")

    with pytest.raises(ImageDownloadError, match="must use HTTP"):
        storage.download_external_url("file:///tmp/cover.png")


def test_image_storage_from_env_uses_local_mock(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """The fake environment setting should select the local implementation."""
    monkeypatch.setenv("IMAGE_STORAGE_FAKE", "1")
    monkeypatch.setenv("IMAGE_STORAGE_MOCK_PATH", str(tmp_path))

    storage = ImageStorage.with_injected()

    assert isinstance(storage, MockImageStorage)
    assert storage.storage_path == tmp_path


def test_minio_image_storage_builds_escaped_public_url() -> None:
    """The MinIO variant should build a public URL without contacting the bucket."""
    storage = MinioImageStorage(
        client=None, bucket="product-images", public_base_url="https://cdn.example.test/images/"
    )

    url = storage.get_file_url("cover image.png")

    assert url == "https://cdn.example.test/images/cover%20image.png"
    assert storage.is_file_url(url) is True
    assert storage.is_file_url("https://images.example.test/cover.png") is False
