"""Shared error rendering helpers for py4web."""

import json
import typing as t

import ombott
from py4web_debug.internals import ContextDict

from common.fixtures import error_ticket_helper
from common.models import auth, auth_context, backend, db, session
from common.models.rendering import render_template
from py4web import HTTP, action, request
from shared_code.data_model import AnyDict
from shared_code.data_model.constants import ROLE_ADMIN

if t.TYPE_CHECKING:
    from shared_code.services.error_tickets import SnapshotDict


def error_renderer_json(context: ContextDict) -> str:
    """Expose a server-error ticket without exception details or traceback."""
    return json.dumps({"code": context["code"], "message": "Interne serverfout", "ticket": context["button_text"]})


class FancyHTTP(HTTP):
    """HTTP exception that renders its body with the common error template."""

    def default_errors(self) -> dict[int, str]:
        """Returns a dictionary of common HTTP error codes and their corresponding descriptions in Dutch."""
        return {
            400: "Ongeldige aanvraag",
            401: "Authenticatie vereist",
            403: "Geen toegang tot deze pagina",
            404: "Niet gevonden",
            405: "Methode niet toegestaan",
            406: "Onacceptabel",
            409: "Conflict",
            410: "Niet (meer) beschikbaar",
            418: "Ik ben een theepot",
            422: "Ongeldige invoer",
            429: "Te veel aanvragen",
            500: "Interne serverfout",
            502: "Ongeldige gateway",
            503: "Dienst niet beschikbaar",
            504: "Gateway-time-out",
        }

    def default_error(self, code: int, fallback: str = "Er ging iets mis") -> str:
        """Returns a human-readable error message based on an error code."""
        return self.default_errors().get(code, fallback)

    def __init__(self, status: int, body: str = "", headers: AnyDict | None = None) -> None:
        """Create an HTTP exception with a rendered error response.

        Args:
            status: HTTP status code to return.
            body: Error message to display on the rendered error page.
            headers: Optional HTTP response headers.

        """
        body = body or self.default_error(status)
        body = generic_error_renderer(status, body)
        super().__init__(status, body, headers=headers)


def current_user_email() -> str:
    """Return the signed-in user's email, or "" when it cannot be determined.

    Error pages cannot use the injected `auth` template variable: since py4web 30a558f
    (release 20250607.2) the fixtures are torn down before a 5xx is rendered. For errors
    raised *inside* the request (`FancyHTTP`, 4xx) the auth context is still live, so
    read it directly; 5xx callers pass the value in from the error snapshot instead.
    """
    try:
        from common.models import auth_context

        user = auth_context.user
    except Exception:
        # never let header rendering break an error page
        return ""

    return (user.email or "") if user else ""


def current_user_is_admin() -> bool:
    """Check the live auth context for errors raised before fixture teardown."""
    try:
        from common.models import auth_context

        return bool(auth_context.user and auth_context.is_admin())
    except Exception:
        return False


@action.uses(session, auth, db)
def _read_error_page_auth() -> tuple[str, bool]:
    """Read the user's role when the failing route had no auth snapshot."""
    user = auth_context.user
    return ((user.email or ""), auth_context.is_admin()) if user else ("", False)


def error_page_auth() -> tuple[str, bool]:
    """Load auth for an error request without an active route fixture chain."""
    try:
        if not getattr(request, "app_name", None):
            request.app_name = "_default"
        return _read_error_page_auth()
    except Exception:
        return "", False


def generic_error_renderer(
    error_code: int,
    text: str,
    subtext: str = "",
    context: t.Any | None = None,
    ticket_id: str = "",
    user_email: str = "",
    is_admin: bool | None = None,
) -> str:
    """Render the common error template with the supplied values."""
    if is_admin is None:
        is_admin = current_user_is_admin()

    return render_template(
        "error.html",
        soort=None,
        output=context if is_admin else {},
        error_code=error_code,
        text=text,
        subtext=subtext,
        ticket_id=ticket_id,
        user_email=user_email or current_user_email(),
        is_admin=is_admin,
    )


def _extract_admin_info(error_snapshot: SnapshotDict | None) -> tuple[bool, str]:
    snapshot_auth = error_snapshot["auth"] if error_snapshot else None
    if snapshot_auth and snapshot_auth.user_groups:
        snapshot_email = snapshot_auth.user_email
        is_admin = bool(snapshot_email and ROLE_ADMIN in snapshot_auth.user_groups)
    else:
        snapshot_email, is_admin = error_page_auth()

    return is_admin, snapshot_email


def error_renderer_5xx(context: ContextDict) -> str:
    """Render a custom error page (5xx)."""
    context["exception"] = str(context.get("exception") or "")

    subtext = ""
    error_code = context["code"]
    text = context["message"]
    error_snapshot = error_ticket_helper.consume() or None

    is_admin, snapshot_email = _extract_admin_info(error_snapshot)

    # note: since py4web 30a558f (release 20250607.2) we don't have access to fixtures (auth/session)
    #  anymore during error rendering.
    ticket_id = backend.error_tickets.try_store(context, snapshot=error_snapshot, applog=True)

    return generic_error_renderer(
        error_code,
        text or "",
        subtext=subtext,
        context=context,
        ticket_id=ticket_id or "",
        user_email=snapshot_email,
        is_admin=is_admin,
    )


def error_renderer_4xx(route: str) -> str:
    """Render the standard 404 page."""
    error_id = 404
    text = "Deze pagina bestaat niet."
    subtext = "Ben je de weg kwijt?"
    user_email, is_admin = error_page_auth()

    return generic_error_renderer(
        error_id,
        text,
        subtext=subtext,
        context=f"De pagina {route} bestaat niet.",
        ticket_id="",  # no tickets for 404
        user_email=user_email,
        is_admin=is_admin,
    )


@ombott.error(404, "/<params:path>")
def url_not_found(route: str, params: str) -> str:
    """Custom 404 page."""
    ombott.response.status = 404
    return error_renderer_4xx(route)
