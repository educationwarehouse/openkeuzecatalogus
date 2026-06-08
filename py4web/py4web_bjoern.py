"""WSGI entrypoint for serving py4web with bjoern."""

# py4web_wsgi.py
# https://py4web.com/_documentation/static/en/chapter-03.html#wsgi

import os

import bjoern
from py4web.core import wsgi


def _start_coverage_if_configured() -> None:  # pragma: no cover
    if os.getenv("COVERAGE_PROCESS_START"):
        import coverage

        coverage.process_startup()


if __name__ == "__main__":
    _start_coverage_if_configured()
    application = wsgi(apps_folder="apps")
    bjoern.run(application, "0.0.0.0", 8000)
