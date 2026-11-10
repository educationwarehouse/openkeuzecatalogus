"""Tests for OLID generation helpers."""

from shared_code.util.olid import generate, generate_supplier_olid, olid_to_isbn


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


def test_generate_olid_for_unregistered_values_uses_readable_slug() -> None:
    """Unregistered keys keep readable slugs while distinct source keys keep their identity."""
    assert generate("method", "didier fle:après la pluie, le beau temps") == (
        "olid://unregistered/method/didier-fle-apres-la-pluie-le-beau-temps#ce1f"
    )
    assert generate("method", "Didier   Fle apres-la-pluie le beau temps") == (
        "olid://unregistered/method/didier-fle-apres-la-pluie-le-beau-temps#0cdd"
    )
    assert generate("method", "Methode #2 / Basis+") == "olid://unregistered/method/methode-2-basis#13c6"


def test_generate_olid_from_ean_url_preserves_the_ean_scheme() -> None:
    """Registered EAN values retain their original hierarchy in the generated OLID."""
    assert generate("product", "ean:1234567890123") == "olid://ean/1234567890123#dc59"


def test_olid_to_isbn_extracts_only_isbn_olids() -> None:
    """ISBN extraction removes the generated hash and rejects other namespaces."""
    assert olid_to_isbn("olid://isbn/9781402894626#91b6") == "9781402894626"
    assert olid_to_isbn("") is None
    assert olid_to_isbn("olid://unregistered/product/example#abcd") is None
