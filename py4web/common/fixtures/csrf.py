"""Same-origin protection for custom browser mutation handlers."""

from urllib.parse import urlsplit

from py4web.core import Fixture

from py4web import HTTP, request


def origin(url: str) -> tuple[str, str | None, int | None]:
    """Compare complete origins, including non-default ports."""
    parsed = urlsplit(url)
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return parsed.scheme, parsed.hostname, port


class SameOrigin(Fixture):
    """Require an exact Origin or Referer for unsafe browser requests."""

    def on_request(self, context: dict) -> None:
        """Reject cross-site mutations before any handler or DAL fixture runs."""
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return

        source = request.headers.get("Origin") or request.headers.get("Referer")

        try:
            allowed = bool(source) and origin(source) == origin(request.url)
        except ValueError:
            allowed = False

        if not allowed:
            raise HTTP(403, "Ongeldige herkomst van de aanvraag. Herlaad de pagina en probeer opnieuw.")


same_origin = SameOrigin()
