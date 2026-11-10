"""Common bootstrap hooks for py4web runtime setup."""

import typing as t

import ombott
from py4web_debug import tools

from py4web import DAL as P4WDAL

from . import settings
from .controllers.error import error_renderer_5xx, error_renderer_json
from .models import db

# Bound multipart/chunked bodies before file decoding and validation.
ombott.default_app().config.max_body_size = settings.REQUEST_MAX_BYTES

tools.enable(
    db=t.cast(P4WDAL, db),
    enabled=True,
    set_env_var=False,
    errorpage_enabled=True,
    errorpage_renderer=error_renderer_5xx,
    errorpage_json_renderer=error_renderer_json,
    debugbar_enabled=False,
)
