"""Write one applog event per request slower than `ROUTE_STATS_SLOW_MS`.

Cannot answer the cache-candidates page: ranking by
`(requests - distinct) * mean` needs every request counted and a distinct count
over request shapes, and neither survives a threshold. What it gives instead is
durable rows, queryable in SQL, at a volume production can carry.
"""

import logging
import typing as t

from endow import GraphBuilder, Service

from shared_code.services.applog import Applogger
from shared_code.services.applog.contracts import ApplogEvent
from shared_code.services.error_tickets import redact_query_params
from shared_code.util.env import int_from_env

logger = logging.getLogger(__name__)

ACTION = "slow_request"

SLOW_MS_VAR = "ROUTE_STATS_SLOW_MS"
DEFAULT_SLOW_MS = 500
# below this the applog queue becomes the slow part
MINIMUM_SLOW_MS = 50


def slow_request_ms() -> int:
    """Return the threshold above which a request is worth an applog event.

    Floored rather than trusted: `0` reads as "log everything", which on a
    production route fills the signal table by accident.
    """
    return max(int_from_env(SLOW_MS_VAR, DEFAULT_SLOW_MS), MINIMUM_SLOW_MS)


class ApplogRouteStats(Service):
    """Report requests slower than a threshold to the applog."""

    applog: Applogger

    def __init__(self, slow_ms: int) -> None:
        """Hold the threshold; the applogger comes from the graph."""
        self.slow_ms = slow_ms

    @classmethod
    def from_env(cls, builder: GraphBuilder, slow_ms: int | None = None) -> t.Self:
        """Build the sink, letting the caller override the threshold.

        The graph builder goes unused, but keeping it first matches the factory
        this overrides.
        """
        return cls(slow_ms=slow_request_ms() if slow_ms is None else slow_ms)

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
        """Write one event, if this request was slow enough to be worth one.

        `signature` and `actor_id` are ignored: the parts are what SQL groups by,
        and who was waiting did not make the route slow. Never raises.
        """
        milliseconds = seconds * 1000
        if milliseconds < self.slow_ms:
            return

        controller_ms = controller_seconds * 1000
        template_ms = template_seconds * 1000
        event: ApplogEvent = {
            "kind": "event",
            "action": ACTION,
            "details": {
                "day": day,
                "route": route,
                "params": redact_query_params(params),
                "anonymous": anonymous,
                "total_ms": round(milliseconds, 1),
                "controller_ms": round(controller_ms, 1),
                "template_ms": round(template_ms, 1),
                # whatever is neither handler nor render: session, auth, db connect and commit
                "overhead_ms": round(max(milliseconds - controller_ms - template_ms, 0), 1),
                # carried along so a query can tell a genuinely slow request from
                # one that only looks slow because the bar was lowered
                "threshold_ms": self.slow_ms,
            },
        }

        try:
            self.applog.try_fire(event)
        except Exception as error:  # telemetry must never break a request
            logger.warning("route stats applog failed: %s: %s", type(error).__name__, error)
