"""What every route-stats sink agrees on: the signature, the protocol, the settings.

`ROUTE_STATS` names a chain, the way `CACHE_BACKEND` does: `redis` keeps the
aggregate counters the cache-candidates page reads, `applog` writes one event
per slow request, and naming both sends every request to both.
"""

import os
import typing as t
from urllib.parse import urlencode

ENABLED_VAR = "ROUTE_STATS"
KNOWN_BACKENDS = ("none", "redis", "applog")

ANONYMOUS = "anon"
IDENTIFIED = "user"


def request_signature(
    route: str,
    params: t.Mapping[str, t.Any],
    anonymous: bool,
    actor_id: str | None = None,
) -> str:
    """Build the string that stands in for the cache key this route would use.

    Sorted so that the same query in a different order counts once, and carrying
    whether the visitor was logged in, plus their stable identifier when they
    were. A per-actor route has roughly as many distinct answers as active users,
    and that is the thing worth spotting before caching it.
    """
    audience = ANONYMOUS if anonymous else f"{IDENTIFIED}:{actor_id}"
    pairs = sorted((str(key), str(value)) for key, value in params.items())
    return f"{route}?{urlencode(pairs)}#{audience}"


def backend_names() -> list[str]:
    """Return the sinks `ROUTE_STATS` asks for, in the order it gives them.

    Unknown names are dropped rather than raised on: this is telemetry, and a
    typo in one variable must not keep the application from starting.
    """
    names: list[str] = []
    for part in os.environ.get(ENABLED_VAR, "none").split(","):
        name = part.strip().lower()
        if name in KNOWN_BACKENDS and name != "none" and name not in names:
            names.append(name)
    return names


class RouteStatsSink(t.Protocol):
    """Somewhere one measured request can be written.

    `signature` is what the redis sink counts distinct shapes of; the applog sink
    ignores it and uses the parts, which are what SQL can group by. Both take
    both, so the fixture measures once and hands the same call to each.
    """

    def record(
        self,
        day: str,
        route: str,
        signature: str,
        seconds: float,
        controller_seconds: float = 0.0,
        template_seconds: float = 0.0,
        params: t.Mapping[str, t.Any] | None = None,
        anonymous: bool = True,
        actor_id: str | None = None,
    ) -> None:
        """Add one request to whatever this sink keeps. Never raises."""
        ...
