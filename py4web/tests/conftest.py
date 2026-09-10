"""Pytest fixtures for py4web tests."""

from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from urllib.parse import urlencode

import pytest
from ombott.router.radirouter import Route

from py4web import request


def _allow_route_overwrite(self: Route, method: list[str] | str, candidate: object) -> None:
    """Let tests import multiple apps that reuse the same route paths."""


# disable errors for duplicate routes:
Route._raise_if_registered = _allow_route_overwrite


def _seed_request_context(app_name: str, path: str) -> None:
    request.environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "testserver",
        "SERVER_PORT": "80",
        "wsgi.url_scheme": "http",
    }
    request.headers = {"accept": "text/html"}
    request.query = {}
    request.query_string = ""
    request.fullpath = path
    request.app_name = app_name


@pytest.fixture()
def default_app_request_context() -> None:
    """Seed the minimal request context needed by decorated `_default` actions."""
    _seed_request_context("_default", "/")


@pytest.fixture()
def admin_app_request_context() -> None:
    """Seed the minimal request context needed by decorated admin actions."""
    _seed_request_context("admin", "/admin/index")


@pytest.fixture()
def request_query() -> Callable[[Mapping[str, str]], AbstractContextManager[None]]:
    """Temporarily set the active request query through Ombott's environment."""

    @contextmanager
    def set_query(params: Mapping[str, str]) -> Iterator[None]:
        original_query_string = request.environ.get("QUERY_STRING", "")
        request.environ["QUERY_STRING"] = urlencode(params)
        try:
            yield
        finally:
            request.environ["QUERY_STRING"] = original_query_string

    return set_query
