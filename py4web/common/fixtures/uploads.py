"""Bound uploaded files before decoding or allocating their complete contents."""

import typing as t

from common import settings
from py4web import HTTP


def read_upload(stream: t.BinaryIO) -> bytes:
    """Read at most one byte beyond the configured per-file limit."""
    content = stream.read(settings.UPLOAD_MAX_BYTES + 1)

    if len(content) > settings.UPLOAD_MAX_BYTES:
        raise HTTP(413, f"Bestand te groot. Maximaal {settings.UPLOAD_MAX_MIB:g} MiB per bestand.")

    return content
