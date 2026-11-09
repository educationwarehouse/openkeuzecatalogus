"""Validate catalogue links and tolerate malformed integer settings."""

import pytest

from shared_code.util.env import int_from_env
from shared_code.util.html import catalog_external_url


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (" https://example.org/demo?q=book#preview ", "https://example.org/demo?q=book#preview"),
        ("http://example.org", "http://example.org"),
        (None, None),
        (123, None),
        ("", None),
        ("/relative/demo", None),
        ("//example.org/demo", None),
        ("javascript:alert(1)", None),
        ("mailto:info@example.org", None),
        ("https:///missing-host", None),
        ("https://[broken", None),
    ],
)
def test_catalogue_external_links_require_an_absolute_http_url(value: object, expected: str | None) -> None:
    """Only usable HTTP(S) links from source data become clickable catalogue links."""
    assert catalog_external_url(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, 17), ("", 17), ("many", 17), ("1.5", 17), (" 42 ", 42), ("0", 0), ("-3", -3)],
)
def test_integer_settings_fall_back_without_losing_valid_values(
    monkeypatch: pytest.MonkeyPatch, value: str | None, expected: int
) -> None:
    """Missing or malformed settings use the supplied default, including empty input."""
    name = "PYTEST_CATALOGUE_INTEGER_SETTING"
    if value is None:
        monkeypatch.delenv(name, raising=False)
    else:
        monkeypatch.setenv(name, value)

    assert int_from_env(name, default=17) == expected
