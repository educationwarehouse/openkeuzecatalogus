"""HTML rendering helpers shared by widgets and filter definitions."""

from urllib.parse import urlsplit


def catalog_external_url(value: object) -> str | None:
    """Accept only absolute HTTP(S) links from catalogue source values."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text.startswith(("https://", "http://")):
        return None
    try:
        return text if urlsplit(text).netloc else None
    except ValueError:
        return None


def convert_attrs[V](attrs: dict[str, V]) -> dict[str, V]:
    """Convert literal HTML attrs into YATL-compatible keyword attrs.

    YATL takes element attributes as `_`-prefixed keywords, which is unreadable for the
    hyphenated ones (`data-bs-toggle`, `aria-expanded`). Write them literally and pass the
    dict through here. Already-prefixed keys are left alone.
    """
    return {(key if key.startswith("_") else f"_{key}"): value for key, value in attrs.items()}
