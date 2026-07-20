"""Tests for the py4web URL helpers."""

from shared_code.infra.web import PY4WEB_URL, _PY4WEB_URL


def test_py4web_url_builds_https_url_from_host_and_path(monkeypatch) -> None:
    """Build URLs from the configured hosting domain and provided path/query."""
    monkeypatch.setenv("HOSTINGDOMAIN", "example.test")

    url = _PY4WEB_URL("foo", "bar", a="1", b="two")

    assert str(url) == "https://example.test/foo/bar?a=1&b=two"
    assert url.scheme == "https"
    assert url.host == "example.test"
    assert url.path == "/foo/bar"
    assert url.query_string == "a=1&b=two"


def test_py4web_url_returns_string_for_yatl_template_usage(monkeypatch) -> None:
    """The public helper should return a plain string URL."""
    monkeypatch.setenv("HOSTINGDOMAIN", "example.test")

    rendered = PY4WEB_URL("auth/entree_mock_authorize", next="dashboard")

    assert rendered == "https://example.test/auth/entree_mock_authorize?next=dashboard"
