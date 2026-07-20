"""Shared fixture helpers for common application routes."""

import json
import typing as t

from py4web.core import Fixture, Template
from py4web.utils.factories import Inject

from py4web import action

from .error_ticket_helper import error_ticket_helper

CommonHelpers = Inject(json=json)


def common(
    template: str | Template | None = None, *optional: Fixture
) -> t.Callable[[t.Callable[..., t.Any]], t.Callable[..., t.Any]]:
    """Attach the standard shared fixtures to a route."""
    from ..models import auth, db, session

    fixtures: list[str | Fixture] = [template] if template is not None else []
    fixtures.extend((session, auth.flash, auth, db, CommonHelpers))
    fixtures.extend(optional)
    fixtures.append(error_ticket_helper)
    return action.uses(*fixtures)
