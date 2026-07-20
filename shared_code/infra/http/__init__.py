"""HTTP and file-backed JSON payload helpers."""

import json
from pathlib import Path
from urllib.parse import unquote

from yayarl import URL

from shared_code.modules.scrapers.types import JsonValue


def fetch_json_payload(
    url: URL,
    timeout: float = 30.0,
    headers: dict[str, str] | None = None,
    allow_redirects: bool = True,
) -> JsonValue:
    """Fetch JSON from HTTP(S) or from a `file://` path."""
    if url.scheme == "file":
        payload_path = Path(unquote(url.path))
        if not payload_path.suffix:
            payload_path = payload_path.with_suffix(".json")
        return json.loads(payload_path.read_text(encoding="utf-8"))

    response = url.get(
        timeout=timeout,
        headers=headers,
        allow_redirects=allow_redirects,
    )
    response.raise_for_status()
    return response.json()


__all__ = ["fetch_json_payload"]
