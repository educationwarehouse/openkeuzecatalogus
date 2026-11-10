"""Image-storage service contract and shared upload helpers."""

import abc
import hashlib
import mimetypes
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from endow import Service
from slugify import slugify

from shared_code.util.env import bool_from_env

type ImageUpload = tuple[str, str]
type ImageDownload = tuple[bytes, str]

MAX_EXTERNAL_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MiB
ALLOWED_EXTERNAL_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


class ImageStorageError(Exception):
    """Base error raised by image-storage implementations."""


class ImageDownloadError(ImageStorageError):
    """Raised when an image cannot be downloaded from its source URL."""


class ImageUploadError(ImageStorageError):
    """Raised when an image cannot be persisted by the configured storage."""


class ImageStorage(Service, abc.ABC):
    """Store imported images and resolve their usable URLs."""

    @abc.abstractmethod
    def upload_bytes(
        self,
        filename: str,
        content: bytes,
        content_type: str | None = None,
    ) -> ImageUpload:
        """Persist bytes under `filename` and return its filename and URL."""
        ...

    @abc.abstractmethod
    def get_file_url(self, filename: str) -> str:
        """Return a usable URL for an already stored filename."""
        ...

    @abc.abstractmethod
    def is_file_url(self, url: str) -> bool:
        """Return whether a URL is already served by this storage backend."""
        ...

    @abc.abstractmethod
    def download_url(self, url: str) -> ImageDownload:
        """Read an image from one of this storage backend's own URLs."""
        ...

    @classmethod
    def from_env(cls) -> ImageStorage:
        """Build the configured image-storage implementation."""
        if bool_from_env("IMAGE_STORAGE_FAKE", default=True):
            from .fake import MockImageStorage

            return MockImageStorage.from_env()
        else:
            from .minio import MinioImageStorage

            return MinioImageStorage.from_env()

    @staticmethod
    def sha1_hash(text: str) -> str:
        """Return the SHA-1 digest used for non-secret filename obfuscation."""
        return hashlib.sha1(text.encode(), usedforsecurity=False).hexdigest()

    @classmethod
    def hash_filename(cls, isbn: str, salt: str | None = None) -> str:
        """Return the salted ISBN hash used as an unpredictable filename prefix."""
        resolved_salt = salt or os.environ.get("IMAGE_STORAGE_HASH_SALT")
        if not resolved_salt:
            raise ValueError("Can't hash an image filename without a storage hash salt")
        return cls.sha1_hash(f"{resolved_salt}_{isbn}")

    @classmethod
    def create_filename(cls, isbn: str, original_filename: str) -> str:
        """Prefix a safe original filename with the salted hash of its ISBN."""
        if not isbn.strip():
            raise ValueError("Can't create an image filename without an ISBN")

        original_name = Path(original_filename.replace("\\", "/")).name
        stem = slugify(Path(original_name).stem) or "image"
        suffix = Path(original_name).suffix.lower()
        safe_filename = f"{stem}{suffix}" if suffix else stem
        return f"{cls.hash_filename(isbn)}_{safe_filename}"

    def upload_from_path(
        self,
        isbn: str,
        source_path: Path | str,
        original_filename: str | None = None,
    ) -> ImageUpload:
        """Read an image from a local path, store it, and return its filename and usable URL."""
        source_path = source_path if isinstance(source_path, Path) else Path(source_path)
        source_name = original_filename or source_path.name or "image"
        filename = self.create_filename(isbn, source_name)

        try:
            content = source_path.read_bytes()
            return self.upload_bytes(filename, content, content_type=self._guess_content_type(filename))

        except OSError as error:
            raise ImageDownloadError(f"Unable to read image from {source_path!r}") from error

    def upload_from_url(
        self,
        isbn: str,
        source_url: str,
        original_filename: str | None = None,
    ) -> ImageUpload:
        """Download an image, store it, and return its filename and usable URL."""
        source_name = original_filename or Path(unquote(urlparse(source_url).path)).name or "image"
        filename = self.create_filename(isbn, source_name)

        content, content_type = self.download_external_url(source_url)
        return self.upload_bytes(filename, content, content_type=content_type or self._guess_content_type(filename))

    def download_external_url(self, source_url: str) -> ImageDownload:
        """Download an image from an HTTP(S) source without storing it."""
        parsed_source_url = urlparse(source_url)
        if parsed_source_url.scheme not in {"http", "https"}:
            raise ImageDownloadError(f"Image URL must use HTTP(S): {source_url!r}")

        try:
            with requests.get(source_url, timeout=10, stream=True) as response:
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if not content_type:
                    content_type = self._guess_content_type(parsed_source_url.path)
                if content_type not in ALLOWED_EXTERNAL_IMAGE_TYPES:
                    raise ImageDownloadError(f"Unsupported image type {content_type!r} at {source_url!r}")

                content_length = response.headers.get("Content-Length")
                if content_length is not None and int(content_length) > MAX_EXTERNAL_IMAGE_BYTES:
                    raise ImageDownloadError(f"Image at {source_url!r} exceeds the size limit")

                content_chunks = []
                content_size = 0
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    content_size += len(chunk)
                    if content_size > MAX_EXTERNAL_IMAGE_BYTES:
                        raise ImageDownloadError(f"Image at {source_url!r} exceeds the size limit")
                    content_chunks.append(chunk)
        except (requests.RequestException, ValueError) as error:
            raise ImageDownloadError(f"Unable to download image from {source_url!r}") from error

        return b"".join(content_chunks), content_type

    @staticmethod
    def _guess_content_type(filename: str) -> str:
        """Infer a content type from a filename with a safe binary fallback."""
        return mimetypes.guess_type(filename)[0] or "application/octet-stream"
