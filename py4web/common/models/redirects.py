"""HTMX-aware redirects and safe `?next` redirect helpers.

Kept separate from :mod:`common.models.request_data` (which pulls in
`common.models.backend`) so that `common.models.backend.auth_forms` can
import these without triggering a circular import back into itself.
"""

import os
import typing as t
from urllib.parse import urlsplit

from py4web import HTTP, request
from py4web import redirect as py4web_redirect


def redirect(location: str) -> t.NoReturn:
    """Preserve the complete destination URL when redirecting HTMX requests."""
    if request.headers.get("HX-Request") == "true":
        raise HTTP(200, headers={"HX-Redirect": location})

    return py4web_redirect(location)


def find_next(default: str) -> str:
    """Return a local or app-domain `next` URL, or `default` when unsafe."""
    try:
        next_url = request.query.get("next")
        if not next_url or next_url != next_url.strip() or "\\" in next_url:
            return default

        parsed_url = urlsplit(next_url)
        if not parsed_url.scheme and not parsed_url.netloc:
            return next_url if next_url.startswith("/") and not next_url.startswith("//") else default

        hostname = parsed_url.hostname
        hosting_domain = os.environ["HOSTINGDOMAIN"].rstrip(".").lower()
        if (
            parsed_url.scheme in {"http", "https"}
            and hostname
            and (hostname == hosting_domain or hostname.endswith(f".{hosting_domain}"))
        ):
            return next_url

        return default
    except Exception:
        # something fishy going on
        return default


def redirect_next(default: str) -> t.NoReturn:
    """Redirect to the validated `next` URL or `default`."""
    return redirect(find_next(default))


__all__ = [
    "find_next",
    "redirect",
    "redirect_next",
]
