"""Tests for admin redirect targets."""

from urllib.parse import urlencode

import pytest
from common.models.redirects import find_next

from py4web import request


@pytest.mark.parametrize(
    ("next_url", "expected"),
    [
        ("/admin/errors?page=2", "/admin/errors?page=2"),
        ("https://fragments.example.test/errors", "https://fragments.example.test/errors"),
        ("https://example.test/errors", "https://example.test/errors"),
        ("https://evil.com", "/admin/errors"),
        ("//evil.com", "/admin/errors"),
        ("https://example.test.evil.com", "/admin/errors"),
    ],
)
def test_find_next_allows_only_local_or_app_domain_urls(
    admin_app_request_context: None, monkeypatch: pytest.MonkeyPatch, next_url: str, expected: str
) -> None:
    """Only local paths and the configured domain's subdomains are allowed."""
    monkeypatch.setenv("HOSTINGDOMAIN", "example.test")
    request.environ["QUERY_STRING"] = urlencode({"next": next_url})

    assert find_next("/admin/errors") == expected
