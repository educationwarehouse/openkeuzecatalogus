"""Helpers for building (py4web) URLs."""

import os

import yayarl as yarl


def _PY4WEB_URL(*path_parts: str, **params: str) -> yarl.URL:
    """Return a yarl URL using the py4web host and provided path/query parts."""
    path = "/".join(path_parts)
    if path[0] != "/":
        path = f"/{path}"
    host = os.environ["HOSTINGDOMAIN"]
    return yarl.URL.build(scheme="https", host=host, path=path, query=params)


def PY4WEB_URL(*path_parts: str, **params: str) -> str:
    """Return a string URL for use in YATL templates."""
    url = _PY4WEB_URL(*path_parts, **params)
    return str(url)
