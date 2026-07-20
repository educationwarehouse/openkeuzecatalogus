"""Domain validation helpers."""

import re
from urllib.parse import urlsplit

from pydal.validators import Validator

_DOMAIN_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.IGNORECASE)


def _normalize_domain(value: str) -> str | None:
    """Return a normalized hostname when *value* contains a valid domain."""
    candidate = value.strip()
    if not candidate:
        return None

    parsed = urlsplit(candidate if "://" in candidate else f"//{candidate}")
    if parsed.username or parsed.password:
        return None

    hostname = parsed.hostname
    if not hostname or "." not in hostname:
        return None

    normalized = hostname.rstrip(".").lower()
    if not normalized or "." not in normalized:
        return None

    labels = normalized.split(".")
    if any(not _DOMAIN_LABEL_RE.fullmatch(label) for label in labels):
        return None

    if labels[-1].isdigit():
        return None

    return normalized


# noinspection PyPep8Naming
class IS_DOMAIN(Validator):
    """Validate and normalize bare domains or URLs containing a domain."""

    def __init__(self, error_message: str = "Ongeldig domein: ") -> None:
        """Initialize the validator with an optional error-message prefix."""
        self.e = error_message

    def __call__(self, value: str, record_id: int | None = None) -> tuple[str | None, str | None]:
        """Return the normalized domain or a validation error tuple for pydal."""
        normalized = _normalize_domain(value)
        if normalized is None:
            return None, f"{self.e}{value!r}"
        return normalized, None
