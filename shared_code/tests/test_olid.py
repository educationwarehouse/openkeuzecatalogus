"""Tests for OLID generation helpers."""

from shared_code.util.olid import generate, generate_supplier_olid


def test_generate_olid_from_https_url_preserves_url_parts() -> None:
    """HTTP URLs should be converted into an OLID with the original URL preserved."""
    assert generate("product", "https://example.test/path/to/item?a=1&b=2#frag") == (
        "olid://https/example.test/path/to/item?a=1&b=2&fragment=frag#ea6b"
    )


def test_generate_olid_from_bare_isbn_uses_isbn_scheme() -> None:
    """Bare ISBN input should be normalized to digits under the isbn hierarchy."""
    assert generate("product", "978-1-4028-9462-6") == "olid://isbn/9781402894626#91b6"


def test_generate_olid_for_unregistered_values_and_supplier_wrapper() -> None:
    """Non-URL values should fall back to the unregistered namespace."""
    assert generate("supplier", "abc123") == "olid://unregistered/supplier/abc123#588f"
    assert generate_supplier_olid("gid-123") == "olid://unregistered/supplier/gid-123#6a6b"
