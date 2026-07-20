"""Email address normalization helpers."""


def normalize_email_for_lookup(email: str | None) -> str:
    """Normalize stored auth emails before extracting domains."""
    normalized = (email or "").strip().lower()
    if normalized.startswith("kennisnet:"):
        normalized = normalized.removeprefix("kennisnet:")

    return normalized


def extract_email_domain(email: str | None) -> str | None:
    """Return the normalized email domain, if the input looks like an email."""
    normalized = normalize_email_for_lookup(email)
    if "@" not in normalized:
        return None

    _, domain = normalized.rsplit("@", 1)
    return domain.strip().lower()
