"""Tests for default py4web route handlers."""

from apps._default.controllers.default import index


def test_default_routes_return_expected_text() -> None:
    """Default routes return expected text responses."""
    assert index() == "hello world"
