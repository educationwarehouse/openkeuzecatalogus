"""Shared error rendering helpers for py4web."""

import typing as t
from pathlib import Path

import ombott
from py4web_debug import is_debug
from py4web_debug.internals import ContextDict

import py4web
from common.fixtures import error_ticket_helper
from py4web import URL
from shared_code.data_model import AnyDict
from shared_code.infra.error_tickets import try_store_ticket

ERROR_CACHE_PATH = Path("/shared_cache") / "errors"
COMMON_PATH = Path("/p4w/common")

IS_DEBUG = is_debug()


def yatl_render(template: str, templates_path: Path | None = None, **context: t.Any) -> str:
    """Render a YATL template from the shared templates directory."""
    templates_path = templates_path or COMMON_PATH / "templates"
    return py4web.render(filename=templates_path / template, path=templates_path, context=context, delimiters="[[ ]]")


def generic_error_renderer(
    error_code: int,
    text: str,
    subtext: str = "",
    context: t.Any | None = None,
    ticket_id: str = "",
) -> str:
    """Render the common error template with the supplied values."""
    return yatl_render(
        "error.html",
        URL=URL,
        soort=None,
        output=context or {},
        error_code=error_code,
        text=text,
        subtext=subtext,
        ticket_id=ticket_id,
    )


def error_renderer_5xx(context: ContextDict) -> str:
    """Render a custom error page (5xx)."""
    context["exception"] = str(context.get("exception") or "")

    subtext = ""
    error_code = context["code"]
    text = context["message"]
    error_snapshot = error_ticket_helper.consume() or None

    try:
        has_authenticated_user = bool(error_snapshot["auth"].user_email)  # type: ignore
    except Exception:
        has_authenticated_user = False

    # note: since py4web 30a558f (release 20250607.2) we don't have access to fixtures (auth/session)
    #  anymore during error rendering.
    ticket_id = try_store_ticket(t.cast(AnyDict, context), snapshot=error_snapshot)

    # todo: ntfy ?

    if not (IS_DEBUG or has_authenticated_user):
        # hide details for anonymous users on production
        context = {}  # type: ignore
        # ticket_id = None

    return generic_error_renderer(
        error_code,
        text or "",
        subtext,
        context,
        ticket_id=ticket_id or "",
    )


def error_renderer_4xx(route: str) -> str:
    """Render the standard 404 page."""
    error_id = 404
    text = "Deze pagina bestaat niet."
    subtext = "Ben je de weg kwijt?"

    return generic_error_renderer(
        error_id,
        text,
        subtext,
        f"De pagina {route} bestaat niet.",
        ticket_id="",  # no tickets for 404
    )


@ombott.error(404, "/<params:path>")
def url_not_found(route: str, params: str) -> str:
    """Custom 404 page."""
    ombott.response.status = 404
    return error_renderer_4xx(route)
