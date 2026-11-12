"""Shared fixture helpers for common application routes."""

import json
import typing as t

from py4web.core import Fixture, Template
from py4web.utils.factories import Inject

from common.constants import BUTTON_CLASS
from py4web import action, request
from shared_code.data_model.constants import ROLE_ADMIN
from shared_code.util.strings import pluralize

from .csrf import same_origin
from .error_ticket_helper import error_ticket_helper
from .route_stats import TimedTemplate, controller_timer, route_stats
from .static_hash import static_hash


class NavigationContext(t.TypedDict):
    """Active shared-navigation state for the current backend route."""

    section: str
    label: str
    current: t.Literal["page", "location"]


def navigation_context() -> NavigationContext:
    """Resolve the shared navigation state from the current backend route."""
    # TODO: derive shared navigation destinations from configurable route metadata.
    path = request.path.rstrip("/") or "/"
    root_segment = path.removeprefix("/").partition("/")[0]

    catalog_routes = {"producten", "pakketten", "methodes", "product", "methode", "supplier", "compare", "favorieten"}
    if root_segment in catalog_routes or path == "/private/catalogus":
        return {"section": "catalogue", "label": "Catalogus", "current": "location"}
    elif path == "/private" or path.startswith("/private/"):
        return {"section": "vision", "label": "Visie-keuzemodule", "current": "location"}
    elif path in {"/", "/index"}:
        return {"section": "home", "label": "Home", "current": "page"}
    elif path in {"/faq", "/faq.html"}:
        return {"section": "faq", "label": "Veelgestelde vragen", "current": "page"}
    elif path == "/admin" or path.startswith("/admin/"):
        return {"section": "admin", "label": "Beheer", "current": "location"}
    elif path.startswith("/auth/"):
        return {"section": "account", "label": "Mijn account", "current": "location"}
    else:
        return {"section": "", "label": "Menu", "current": "location"}


CommonHelpers = Inject(
    json=json,
    pluralize=pluralize,
    BUTTON_CLASS=BUTTON_CLASS,
    navigation_context=navigation_context,
)


def _tracked(template: str | Template | Fixture | None) -> str | Template | Fixture | None:
    """Swap a template name for one that times its own rendering, while tracking is on.

    With `ROUTE_STATS=none` there is nobody to report to, so the plain Template
    goes in and no wrapper sits in the request path. A caller that built its own
    Template instance keeps it either way.
    """
    if not route_stats.enabled or not isinstance(template, str):
        return template
    return TimedTemplate(template)


def _timers(fixtures: list[str | Fixture]) -> list[str | Fixture]:
    """Append the handler timer, while tracking is on.

    Last in the list, so py4web's reversed `on_success` makes its window the
    handler body and nothing around it.
    """
    if route_stats.enabled:
        fixtures.append(controller_timer)
    return fixtures


def common(
    template: str | Template | Fixture | None = None, *optional: Fixture
) -> t.Callable[[t.Callable[..., t.Any]], t.Callable[..., t.Any]]:
    """Attach the standard shared fixtures to a route."""
    from ..models import auth, db, session
    from ..models.backend.session import grid_action_signer

    # route_stats first: py4web runs on_request forwards and on_success backwards,
    # so only the first fixture sees the whole request, template rendering included
    fixtures: list[str | Fixture] = [route_stats]
    if (tracked := _tracked(template)) is not None:
        fixtures.append(tracked)
    fixtures.append(same_origin)
    fixtures.extend((session, grid_action_signer, auth.flash, auth, db, CommonHelpers, static_hash))
    fixtures.extend(optional)
    fixtures.append(error_ticket_helper)
    return action.uses(*_timers(fixtures))


def admin(
    template: str | Template | Fixture | None = None, *optional: Fixture
) -> t.Callable[[t.Callable[..., t.Any]], t.Callable[..., t.Any]]:
    """Apply the standard admin fixture chain to a handler."""
    from ..models import auth, db, session
    from ..models.backend.session import grid_action_signer

    # route_stats first, for the same reason as in common()
    fixtures: list[str | Fixture] = [route_stats]
    if (tracked := _tracked(template)) is not None:
        fixtures.append(tracked)
    fixtures.append(same_origin)
    fixtures.extend(
        (
            session,
            grid_action_signer,
            auth.flash,
            auth,
            auth.user,
            auth.requires_membership(ROLE_ADMIN),
            db,
            CommonHelpers,
            static_hash,
        )
    )
    fixtures.extend(optional)
    fixtures.append(error_ticket_helper)  # last of the real fixtures, for optimal context
    return action.uses(*_timers(fixtures))
