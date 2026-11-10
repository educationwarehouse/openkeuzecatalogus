"""MinIO-backed implementation for S3-compatible image storage."""

import io
import os
import traceback
from urllib.parse import quote, unquote, urlparse

from minio import Minio
from minio.error import MinioException

from .contracts import ImageDownload, ImageDownloadError, ImageStorage, ImageUpload, ImageUploadError


class MinioImageStorage(ImageStorage):
    """Store images in an S3-compatible bucket through the MinIO client."""

    def __init__(self, client: Minio, bucket: str, public_base_url: str) -> None:
        """Initialize the bucket client and stable public URL base."""
        self.client = client
        self.bucket = bucket
        self.public_base_url = public_base_url.rstrip("/")

    @classmethod
    def from_env(cls) -> MinioImageStorage:
        """Build an S3-compatible image store from environment configuration."""
        endpoint_url = os.environ.get("IMAGE_STORAGE_ENDPOINT_URL", "")
        bucket = os.environ.get("IMAGE_STORAGE_BUCKET", "")
        access_key = os.environ.get("IMAGE_STORAGE_ACCESS_KEY_ID", "")
        secret_key = os.environ.get("IMAGE_STORAGE_SECRET_ACCESS_KEY", "")
        public_base_url = os.environ.get("IMAGE_STORAGE_PUBLIC_BASE_URL", "")
        if not all((endpoint_url, bucket, access_key, secret_key, public_base_url)):
            raise OSError("Incomplete image storage configuration")

        parsed_endpoint = urlparse(endpoint_url if "://" in endpoint_url else f"https://{endpoint_url}")
        endpoint = parsed_endpoint.netloc
        if not endpoint:
            raise OSError("IMAGE_STORAGE_ENDPOINT_URL must contain a hostname")

        client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=parsed_endpoint.scheme != "http",
        )
        return cls(client=client, bucket=bucket, public_base_url=public_base_url)

    def upload_bytes(
        self,
        filename: str,
        content: bytes,
        content_type: str | None = None,
    ) -> ImageUpload:
        """Upload bytes to the bucket and return their filename and public URL."""
        try:
            self.client.put_object(
                self.bucket,
                filename,
                io.BytesIO(content),
                length=len(content),
                content_type=content_type or self._guess_content_type(filename),
            )
        except MinioException as error:
            traceback.print_exc()
            raise ImageUploadError(f"Unable to upload image {filename!r}") from error
        return filename, self.get_file_url(filename)

    def get_file_url(self, filename: str) -> str:
        """Return the stable public URL for a bucket object."""
        return f"{self.public_base_url}/{quote(filename, safe='._-')}"

    def is_file_url(self, url: str) -> bool:
        """Return whether a URL belongs to this storage bucket's public base URL."""
        return url.startswith(f"{self.public_base_url}/")

    def download_url(self, url: str) -> ImageDownload:
        """Read one image from this storage bucket by its public URL."""
        if not self.is_file_url(url):
            raise ImageDownloadError(f"Image URL is not served by this storage backend: {url!r}")

        filename = unquote(url.removeprefix(f"{self.public_base_url}/"))
        if not filename or "/" in filename:
            raise ImageDownloadError(f"Invalid image URL: {url!r}")

        try:
            response = self.client.get_object(self.bucket, filename)
            try:
                content = response.read()
                content_type = response.headers.get("Content-Type") or self._guess_content_type(filename)
                return content, content_type
            finally:
                response.close()
                response.release_conn()
        except MinioException as error:
            raise ImageDownloadError(f"Unable to read image from {url!r}") from error
