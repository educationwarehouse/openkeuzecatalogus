"""Tests for the local image-storage implementation."""

import hashlib
import typing as t
from pathlib import Path
from urllib.parse import quote

from shared_code.services.images import ImageStorage, MinioImageStorage, MockImageStorage

if t.TYPE_CHECKING:
    from pytest import MonkeyPatch


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


def test_image_storage_from_env_uses_local_mock(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """The fake environment setting should select the local implementation."""
    monkeypatch.setenv("IMAGE_STORAGE_FAKE", "1")
    monkeypatch.setenv("IMAGE_STORAGE_MOCK_PATH", str(tmp_path))

    storage = ImageStorage.from_env()

    assert isinstance(storage, MockImageStorage)
    assert storage.storage_path == tmp_path


def test_minio_image_storage_builds_escaped_public_url() -> None:
    """The MinIO variant should build a public URL without contacting the bucket."""
    storage = MinioImageStorage(client=None, bucket="product-images", public_base_url="https://cdn.example.test/images/")

    url = storage.get_file_url("cover image.png")

    assert url == "https://cdn.example.test/images/cover%20image.png"
    assert storage.is_file_url(url) is True
    assert storage.is_file_url("https://images.example.test/cover.png") is False
