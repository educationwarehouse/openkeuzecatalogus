"""Tests for domain validation helpers."""

from shared_code.data_model.validators.is_domain import IS_DOMAIN


def test_is_domain_accepts_bare_domain_and_normalizes_case() -> None:
    """Accept bare domains and normalize whitespace/casing."""
    validator = IS_DOMAIN()

    parsed, error = validator("  Example.NL ")

    assert parsed == "example.nl"
    assert error is None


def test_is_domain_accepts_url_and_extracts_hostname() -> None:
    """Accept URLs and return the hostname."""
    validator = IS_DOMAIN()

    parsed, error = validator("https://sub.example.nl/path?q=1")

    assert parsed == "sub.example.nl"
    assert error is None


def test_is_domain_rejects_single_label_hostnames() -> None:
    """Reject hostnames without a dot-separated domain."""
    validator = IS_DOMAIN(error_message="Invalid domain: ")

    parsed, error = validator("localhost")

    assert parsed is None
    assert error == "Invalid domain: 'localhost'"


def test_is_domain_rejects_email_addresses() -> None:
    """Reject email addresses instead of silently extracting their domain."""
    validator = IS_DOMAIN(error_message="Invalid domain: ")

    parsed, error = validator("admin@example.nl")

    assert parsed is None
    assert error == "Invalid domain: 'admin@example.nl'"
