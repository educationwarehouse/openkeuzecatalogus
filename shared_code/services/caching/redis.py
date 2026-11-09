"""Redis-backed cache service.

Uses its own logical Redis database so the cache keyspace never collides with
py4web's session store, which sits on database 0.

Key layout, all under one prefix:

    <prefix>:v:<key>     the serialized value
    <prefix>:k:<key>     the set of dependency tokens that entry recorded
    <prefix>:d:<token>   the reverse index: which entries recorded that token
    <prefix>:lock:<key>  the single-flight lock, when a call site asks for one

The reverse index is what makes `invalidate(gid)` one lookup instead of a scan.
"""

import math
import os
import typing as t

import redis
from endow import GraphBuilder
from redis.exceptions import WatchError
from redis.lock import Lock

from .contracts import CacheService
from .helpers import dep_token as dep_token
from .helpers import dep_tokens, table_invalidation_tokens, table_invalidation_tokens_many, ttl_seconds
from .types import TTL, DepSet, GidDep

DEFAULT_PREFIX = "okc:cache"
DEFAULT_HOST = "redis-master"
DEFAULT_PORT = 6379
DEFAULT_DB = 1
DEFAULT_LOCK_TIMEOUT = 30
SCAN_BATCH = 500
INVALIDATION_RETRIES = 5


def _milliseconds(ttl: TTL) -> int | None:
    """Round a positive ttl up to Redis milliseconds, or preserve no expiry."""
    seconds = ttl_seconds(ttl)
    return None if seconds is None else math.ceil(seconds * 1000)


class RedisCacheService(CacheService):
    """Store cache entries and their dependency index in Redis."""

    def __init__(
        self,
        client: redis.Redis,
        prefix: str = DEFAULT_PREFIX,
        lock_timeout: int = DEFAULT_LOCK_TIMEOUT,
    ) -> None:
        """Wrap an existing Redis client with the cache's key layout."""
        self.client = client
        self.prefix = prefix
        self.lock_timeout = lock_timeout
        self._locks: dict[str, Lock] = {}

    @classmethod
    def from_env(
        cls,
        builder: GraphBuilder,
        client: redis.Redis | None = None,
        prefix: str | None = None,
        lock_timeout: int | None = None,
    ) -> t.Self:
        """Build a Redis cache, letting the caller override any part of it.

        Connection details come from `REDIS_CACHE_HOST`, `REDIS_CACHE_PORT` and
        `REDIS_CACHE_DB`, which defaults to 1 so the cache stays clear of
        py4web's sessions on 0. Redis replicates every logical database, so this
        separates the cache from py4web's keys, not from the replica.

        The graph builder goes unused, but keeping it first matches the factory
        this overrides, so a caller holding the abstract type can still use it.
        """
        if client is None:
            client = redis.Redis(
                host=os.environ.get("REDIS_CACHE_HOST") or DEFAULT_HOST,
                port=int(os.environ.get("REDIS_CACHE_PORT") or DEFAULT_PORT),
                db=int(os.environ.get("REDIS_CACHE_DB") or DEFAULT_DB),
                password=os.environ.get("REDIS_PASSWORD"),
            )

        return cls(
            client,
            prefix=prefix or os.environ.get("CACHE_PREFIX") or DEFAULT_PREFIX,
            lock_timeout=lock_timeout or int(os.environ.get("CACHE_LOCK_TIMEOUT") or DEFAULT_LOCK_TIMEOUT),
        )

    # --- key layout ---

    def value_key(self, key: str) -> str:
        """Return the Redis key holding one entry's payload."""
        return f"{self.prefix}:v:{key}"

    def deps_key(self, key: str) -> str:
        """Return the Redis key holding one entry's dependency tokens."""
        return f"{self.prefix}:k:{key}"

    def index_key(self, token: str) -> str:
        """Return the Redis key holding the reverse index for one dependency."""
        return f"{self.prefix}:d:{token}"

    def lock_key(self, key: str) -> str:
        """Return the Redis key holding one entry's single-flight lock."""
        return f"{self.prefix}:lock:{key}"

    # --- contract ---

    def load_entry(self, key: str) -> tuple[bool, bytes | None]:
        """Return a stored payload. Redis drops expired keys itself."""
        payload = self.client.get(self.value_key(key))
        if payload is None:
            return False, None
        return True, t.cast(bytes, payload)

    def store_entry(self, key: str, payload: bytes, deps: DepSet, ttl: TTL) -> None:
        """Write a payload and index it under every dependency it recorded."""
        milliseconds = _milliseconds(ttl)
        if milliseconds is not None and milliseconds <= 0:
            # already expired on arrival; storing it would only serve stale data
            self.client.delete(self.value_key(key), self.deps_key(key))
            return

        tokens = dep_tokens(deps)

        pipe = self.client.pipeline()
        pipe.set(self.value_key(key), payload, px=milliseconds)
        pipe.delete(self.deps_key(key))

        if tokens:
            pipe.sadd(self.deps_key(key), *tokens)
            self._keep_alive(pipe, self.deps_key(key), milliseconds)

            for token in tokens:
                index = self.index_key(token)
                pipe.sadd(index, key)
                self._keep_alive(pipe, index, milliseconds)

        pipe.execute()

    def drop_by_gid(self, gid: str) -> int:
        """Drop every entry that recorded this gid, and clean up after them."""
        return self._drop_tokens({dep_token(GidDep(gid))})

    def drop_by_table(self, table: str, gid: str | None = None) -> int:
        """Use dependency indexes, without scanning unrelated cache keys."""
        return self._drop_tokens(table_invalidation_tokens(table, gid=gid))

    def drop_by_table_many(self, table: str, gids: t.Collection[str]) -> int:
        """Invalidate the combined dependency indexes in one transaction."""
        return self._drop_tokens(table_invalidation_tokens_many(table, gids=gids))

    def drop_all(self) -> int:
        """Drop every key this cache owns, leaving anything else in the database alone."""
        dropped = 0
        batch: list[str] = []

        for raw in self.client.scan_iter(match=f"{self.prefix}:*", count=SCAN_BATCH):
            name = raw.decode() if isinstance(raw, bytes) else str(raw)
            if name.startswith(f"{self.prefix}:v:"):
                dropped += 1
            batch.append(name)
            if len(batch) >= SCAN_BATCH:
                self.client.delete(*batch)
                batch.clear()

        if batch:
            self.client.delete(*batch)

        return dropped

    def take_lock(self, key: str, wait: bool = False) -> bool:
        """Take a single-flight lock, optionally waiting for its current owner."""
        lock = self.client.lock(self.lock_key(key), timeout=self.lock_timeout)
        acquired = (
            lock.acquire(blocking=True, blocking_timeout=self.lock_timeout) if wait else lock.acquire(blocking=False)
        )
        if acquired:
            self._locks[key] = lock
        return bool(acquired)

    def drop_lock(self, key: str) -> None:
        """Release a single-flight lock."""
        lock = self._locks.pop(key, None)
        if lock is not None:
            lock.release()

    # --- internals ---

    @staticmethod
    def _keep_alive(pipe: redis.client.Pipeline, name: str, milliseconds: int | None) -> None:
        """Keep an index set alive at least as long as its longest-lived member."""
        if milliseconds is None:
            # an entry that never expires must stay findable forever
            pipe.persist(name)
        else:
            # NX assigns a TTL when SADD just created the set. GT then keeps an
            # existing set alive for its longest-lived member.
            pipe.pexpire(name, milliseconds, nx=True)
            pipe.pexpire(name, milliseconds, gt=True)

    def _drop_tokens(self, tokens: set[str]) -> int:
        """Drop indexed entries and dependency links in one transaction."""
        if not tokens:
            return 0
        indexes = [self.index_key(token) for token in tokens]
        for _ in range(INVALIDATION_RETRIES):
            with self.client.pipeline() as pipe:
                try:
                    pipe.watch(*indexes)
                    keys = [
                        member.decode() if isinstance(member, bytes) else str(member) for member in pipe.sunion(indexes)
                    ]
                    deps_keys = [self.deps_key(key) for key in keys]
                    if deps_keys:
                        pipe.watch(*deps_keys)
                    dependencies = [pipe.smembers(deps_key) for deps_key in deps_keys]

                    pipe.multi()
                    for key, deps_key, entry_tokens in zip(keys, deps_keys, dependencies, strict=True):
                        for raw in entry_tokens:
                            dep = raw.decode() if isinstance(raw, bytes) else str(raw)
                            pipe.srem(self.index_key(dep), key)
                        pipe.delete(self.value_key(key), deps_key)
                    pipe.delete(*indexes)
                    pipe.execute()
                    return len(keys)
                except WatchError:
                    continue
        raise WatchError(f"Cache invalidation could not complete for {tokens!r}")
