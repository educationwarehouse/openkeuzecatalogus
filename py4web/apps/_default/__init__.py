from py4web_debug import is_debug, tools

from .models import db

tools.enable(
    db=db,
    enabled=is_debug(),
    errorpage_enabled=True,
    debugbar_enabled=False,
)

from . import controllers  # noqa: E402 - otherwise debug tools won't apply to the controllers

__all__ = ["controllers", "db"]
