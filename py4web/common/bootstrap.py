"""Common bootstrap hooks for py4web runtime setup."""

from py4web_debug import is_debug, tools

from .controllers.error import error_renderer_5xx
from .models import db

tools.enable(
    db=db,
    enabled=is_debug(),
    errorpage_enabled=True,
    errorpage_renderer=error_renderer_5xx,
    debugbar_enabled=False,
)
