"""Fixture that exposes a cache-busting `STATIC` helper to yatl templates."""

import os
from pathlib import Path

from py4web.core import Fixture, request

from py4web import URL
from shared_code.data_model import AnyDict

# py4web sets PY4WEB_APPS_FOLDER on startup; fall back to this package's sibling `apps`
# directory so the fixture also works outside a served request (tests, shell).
APPS_FOLDER = Path(os.environ.get("PY4WEB_APPS_FOLDER") or Path(__file__).parents[2] / "apps")


class StaticHash(Fixture):
    """Add a `STATIC` helper to the template context that appends a content hash.

    The hash lets the browser tell a rebuilt bundle apart from its cached copy.
    `.hash` files are written by `ew bundle.build` when `config.hash` is
    enabled in `bundle.yaml`.
    """

    @property
    def app_name(self) -> str:
        """Return the app handling the current request."""
        return getattr(request, "app_name", "_default")

    def url_with_hash(self, folder: str, filename: str, app_name: str | None = None, **kwargs: object) -> str:
        """Build a static URL for the requested app with a `hash` query parameter.

        Example: `STATIC("css", "bundled-latest.css")`
        -> `/private/static/css/bundled-latest.css?hash=345...124`
        Use `app_name="_default"` to load a shared root asset from another app.
        """
        if file_hash := self._get_hash(folder, filename, app_name=app_name):
            kwargs.setdefault("vars", {"hash": file_hash})

        if app_name is not None:
            kwargs["use_appname"] = False
            if app_name != "_default":
                return URL(app_name, "static", folder, filename, **kwargs)

        return URL("static", folder, filename, **kwargs)

    def on_success(self, context: AnyDict) -> None:
        """Inject the `STATIC` helper into a dict output before it is rendered."""
        if isinstance(output := context.get("output"), dict):
            output.setdefault("STATIC", self.url_with_hash)

    def _get_hash(self, folder: str, filename: str, app_name: str | None = None) -> str:
        """Read the latest build hash, also when assets were rebuilt after startup."""
        hash_file = APPS_FOLDER / (app_name or self.app_name) / "static" / folder / f"{filename}.hash"
        try:
            return hash_file.read_text().strip()
        except FileNotFoundError:
            return ""


static_hash = StaticHash()

__all__ = ["APPS_FOLDER", "StaticHash", "static_hash"]
