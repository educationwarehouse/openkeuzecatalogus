"""Helpers for rendering shared YATL templates."""

import typing as t
from pathlib import Path

import py4web
from py4web import URL

COMMON_PATH = Path("/p4w/common")


def yatl_render(template: str, templates_path: Path | None = None, **context: t.Any) -> str:
    """Render a YATL template from the shared templates directory."""
    templates_path = templates_path or COMMON_PATH / "templates"
    return py4web.render(filename=templates_path / template, path=templates_path, context=context, delimiters="[[ ]]")


def render_template(
    template: str,
    templates_path: Path | None = None,
    **context: t.Any,
) -> str:
    """Render a shared template with ``URL`` available in its context."""
    context.setdefault("URL", URL)
    return yatl_render(template, templates_path=templates_path, **context)
