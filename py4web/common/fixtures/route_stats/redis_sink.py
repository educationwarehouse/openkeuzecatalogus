"""Count requests, distinct request shapes and time spent, per route.

Which routes are worth wrapping in a cache block: a slow route whose every
request looks different can never hit one, so `report()` ranks by
`(requests - distinct) * mean_seconds`, the time a perfect cache would have
saved. Distinct counting uses a HyperLogLog, so raw signatures are never
stored.

This is the sink that can be read back: it is what the cache-candidates admin
page queries. `ROUTE_STATS=applog` records events instead and leaves the page
with nothing to show, which is why that page hides unless `redis` is in the
chain.
"""

import logging
import os
import typing as t

import redis

from shared_code.util.counters import RedisCounters

logger = logging.getLogger(__name__)

DEFAULT_PREFIX = "okc:routestats"
DEFAULT_RETENTION_DAYS = 30
DEFAULT_HOST = "redis-master"
DEFAULT_PORT = 6379
DEFAULT_DB = 1


class RouteStats:
    """Accumulate per-route counters."""

    def __init__(
        self,
        client: redis.Redis,
        prefix: str = DEFAULT_PREFIX,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ) -> None:
        """Wrap a Redis client with the per-route key layout."""
        self.prefix = prefix
        self.counters = RedisCounters(client, retention_seconds=retention_days * 24 * 60 * 60)

    @classmethod
    def from_env(cls) -> RouteStats:
        """Build the counters on their own client, from the variables the cache uses.

        Its own connection rather than py4web's session client: importing that
        here would close a cycle through `common.models`, and the counters have
        no business on database 0 next to the sessions.
        """
        client = redis.Redis(
            host=os.environ.get("REDIS_CACHE_HOST") or DEFAULT_HOST,
            port=int(os.environ.get("REDIS_CACHE_PORT") or DEFAULT_PORT),
            db=int(os.environ.get("REDIS_CACHE_DB") or DEFAULT_DB),
            password=os.environ.get("REDIS_PASSWORD"),
        )
        return cls(client)

    def _key(self, day: str, route: str, kind: str) -> str:
        return f"{self.prefix}:{day}:{route}:{kind}"

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
        """Add one request to the counters, split into the parts that were measured.

        `controller_seconds` is the handler body and `template_seconds` the
        render. What is left of `seconds` is the fixtures around them: session,
        auth, the database connection and its commit.

        `params`, `anonymous` and `actor_id` are already folded into `signature`
        and are accepted only so the fixture can hand every sink the same call.

        Never raises: this runs on every request and a broken stats backend must
        not be able to fail one.
        """
        try:
            self.counters.observe(
                counted=self._key(day, route, "requests"),
                unique=self._key(day, route, "signatures"),
                member=signature,
                sums={
                    self._key(day, route, "seconds"): seconds,
                    self._key(day, route, "controller_seconds"): controller_seconds,
                    self._key(day, route, "template_seconds"): template_seconds,
                },
            )
        except Exception as error:  # telemetry must never break a request
            logger.warning("route stats failed: %s: %s", type(error).__name__, error)

    def routes(self, day: str) -> list[str]:
        """Return every route recorded on one day."""
        marker = f"{self.prefix}:{day}:"
        suffix = ":requests"
        found = {name[len(marker) : -len(suffix)] for name in self.counters.keys_matching(f"{marker}*{suffix}")}
        return sorted(found)

    def report(self, day: str) -> list[dict[str, t.Any]]:
        """Rank one day's routes by the time a perfect cache would have saved."""
        rows = []
        for route in self.routes(day):
            requests = self.counters.count(self._key(day, route, "requests"))
            if not requests:
                continue

            distinct = self.counters.distinct_count(self._key(day, route, "signatures"))
            seconds = self.counters.total(self._key(day, route, "seconds"))
            controller = self.counters.total(self._key(day, route, "controller_seconds"))
            template = self.counters.total(self._key(day, route, "template_seconds"))
            mean = seconds / requests

            rows.append(
                {
                    "route": route,
                    "requests": requests,
                    "distinct": distinct,
                    "total_seconds": round(seconds, 3),
                    "mean_seconds": round(mean, 4),
                    "mean_controller_seconds": round(controller / requests, 4),
                    "mean_template_seconds": round(template / requests, 4),
                    # whatever is neither handler nor render: session, auth, db connect and commit
                    "mean_overhead_seconds": round(max(seconds - controller - template, 0) / requests, 4),
                    # what a cache that never missed twice on the same shape would have saved
                    "saved_seconds": round(max(requests - distinct, 0) * mean, 3),
                }
            )

        return sorted(rows, key=lambda row: row["saved_seconds"], reverse=True)

    def clear(self, day: str | None = None) -> int:
        """Drop the counters for one day, or every day when none is given.

        Useful after a change that makes older numbers incomparable, which is
        what a measurement fix does.
        """
        pattern = f"{self.prefix}:{day}:*" if day else f"{self.prefix}:*"
        return self.counters.drop_matching(pattern)

    def summary(self, day: str) -> dict[str, t.Any]:
        """Return one day's headline numbers, for a dashboard tile."""
        rows = self.report(day)
        return {
            "routes": len(rows),
            "requests": sum(int(row["requests"]) for row in rows),
            "saved_seconds": round(sum(float(row["saved_seconds"]) for row in rows), 1),
        }
