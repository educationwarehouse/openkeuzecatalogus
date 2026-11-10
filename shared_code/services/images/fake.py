"""Local image-storage implementation for development and tests."""

import os
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from .contracts import ImageDownload, ImageDownloadError, ImageStorage, ImageUpload


class MockImageStorage(ImageStorage):
    """Store images locally and expose them as file:// URLs."""

    def __init__(self, storage_path: Path) -> None:
        """Create a local image store rooted at `storage_path`."""
        self.storage_path = storage_path

    @classmethod
    def from_env(cls) -> MockImageStorage:
        """Build a local image store from its configured filesystem path."""
        return cls(Path(os.environ.get("IMAGE_STORAGE_MOCK_PATH", "/shared_cache/image_uploads")))

    def upload_bytes(
        self,
        filename: str,
        content: bytes,
        content_type: str | None = None,
    ) -> ImageUpload:
        """Persist bytes locally and return their file:// URL."""
        file_path = self._file_path(filename)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(content)
        return filename, self.get_file_url(filename)

    def get_file_url(self, filename: str) -> str:
        """Return the local file:// URL for an already stored filename."""
        return f"file://{quote(str(self._file_path(filename)))}"

    def upload_from_url(
        self,
        isbn: str,
        source_url: str,
        original_filename: str | None = None,
    ) -> ImageUpload:
        """Store local file URLs; delegate all other URL schemes to the base class."""
        parsed_source_url = urlparse(source_url)
        if parsed_source_url.scheme == "file":
            if parsed_source_url.netloc not in ("", "localhost"):
                raise ImageDownloadError(f"Unable to download image from {source_url!r}")
            return self.upload_from_path(isbn, unquote(parsed_source_url.path), original_filename)
        return super().upload_from_url(isbn, source_url, original_filename)

    def is_file_url(self, url: str) -> bool:
        """Return whether a URL points at this mock's local storage root."""
        return url.startswith(f"file://{quote(str(self.storage_path))}/")

    def download_url(self, url: str) -> ImageDownload:
        """Read one image stored by this local backend."""
        if not self.is_file_url(url):
            raise ImageDownloadError(f"Image URL is not served by this storage backend: {url!r}")

        try:
            image_path = Path(unquote(urlparse(url).path))
            return image_path.read_bytes(), self._guess_content_type(image_path.name)
        except OSError as error:
            raise ImageDownloadError(f"Unable to read image from {url!r}") from error

    def _file_path(self, filename: str) -> Path:
        """Resolve a filename safely inside the configured local storage root."""
        if Path(filename).name != filename:
            raise ValueError("Image filename must not contain a path")
        return self.storage_path / filename
