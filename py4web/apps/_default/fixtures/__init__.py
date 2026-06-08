import json
import typing as t

from py4web.core import Fixture, Template
from py4web.utils.factories import Inject

from py4web import action

from ..models.auth import auth, db, session

CommonHelpers = Inject(json=json)


def common(
    template: str | Template | None, *optional: Fixture
) -> t.Callable[[t.Callable[..., t.Any]], t.Callable[..., t.Any]]:
    fixtures: list[str | Fixture] = [template] if template is not None else []
    fixtures.extend((session, flash, auth, db, CommonHelpers))
    fixtures.extend(optional)
    return action.uses(*fixtures)


auth.enable(route="auth", uses=(CommonHelpers,))

flash = auth.flash


__all__ = [
    "auth",
    "common",
]
