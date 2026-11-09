"""Named counter operations backed by Redis.

Exists so callers count things instead of writing Redis verbs: every `incr`,
`pfadd` and `expire` lives here.
"""

import typing as t

import redis

SCAN_BATCH = 500


class RedisCounters:
    """Counts, distinct-sets and running totals, all expiring after one window."""

    def __init__(self, client: redis.Redis, retention_seconds: int) -> None:
        """Wrap a Redis client with a retention window for everything it stores."""
        self.client = client
        self.retention_seconds = retention_seconds

    def observe(self, *, counted: str, unique: str, member: str, sums: t.Mapping[str, float]) -> None:
        """Add one observation to a count, a distinct-set and any running totals.

        `sums` maps a key to the amount to add to it, so a caller that measures
        one request in several parts records them all in one round trip.
        """
        pipe = self.client.pipeline()
        pipe.incr(counted)
        pipe.pfadd(unique, member)
        for key, amount in sums.items():
            pipe.incrbyfloat(key, amount)
        for key in (counted, unique, *sums):
            pipe.expire(key, self.retention_seconds)
        pipe.execute()

    def count(self, key: str) -> int:
        """Return how many observations a counter saw."""
        return int(self.client.get(key) or 0)

    def distinct_count(self, key: str) -> int:
        """Return roughly how many different members a distinct-set saw."""
        return int(self.client.pfcount(key) or 0)

    def total(self, key: str) -> float:
        """Return the running total of a summed counter."""
        return float(self.client.get(key) or 0.0)

    def keys_matching(self, pattern: str) -> t.Iterator[str]:
        """Yield every stored key matching a glob."""
        for raw in self.client.scan_iter(match=pattern, count=SCAN_BATCH):
            yield raw.decode() if isinstance(raw, bytes) else str(raw)

    def drop_matching(self, pattern: str) -> int:
        """Delete every stored key matching a glob, returning how many went.

        Deletes in batches while scanning, so a large keyspace never has to be
        held in memory at once.
        """
        dropped = 0
        batch: list[str] = []

        for name in self.keys_matching(pattern):
            batch.append(name)
            if len(batch) >= SCAN_BATCH:
                dropped += int(self.client.delete(*batch))
                batch.clear()

        if batch:
            dropped += int(self.client.delete(*batch))

        return dropped
