"""Per-route timing, recorded into whatever sinks `ROUTE_STATS` names.

`ROUTE_STATS` takes a chain, the way `CACHE_BACKEND` does:

- `none` records nothing and keeps the timing fixtures out of the request path.
- `redis` keeps the aggregate counters behind the cache-candidates admin page.
- `applog` writes one durable event per request slower than
  `ROUTE_STATS_SLOW_MS`.
- `redis,applog` does both.

The applog sink itself is a backend service (`common.models.backend.route_stats`),
since it needs the applogger the graph wires.
"""

from .contracts import ENABLED_VAR, RouteStatsSink, backend_names, request_signature
from .fixtures import (
    CONTROLLER_SECONDS,
    STARTED_AT,
    TEMPLATE_SECONDS,
    ControllerTimerFixture,
    RouteStatsFixture,
    TimedTemplate,
    controller_timer,
    route_stats,
)
from .redis_sink import RouteStats

__all__ = [
    "CONTROLLER_SECONDS",
    "ENABLED_VAR",
    "STARTED_AT",
    "TEMPLATE_SECONDS",
    "ControllerTimerFixture",
    "RouteStats",
    "RouteStatsFixture",
    "RouteStatsSink",
    "TimedTemplate",
    "backend_names",
    "controller_timer",
    "request_signature",
    "route_stats",
]
