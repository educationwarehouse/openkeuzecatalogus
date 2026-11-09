"""In-process cache backends: one that remembers, one that never does.

`MemoryCacheService` is the test double and the local-development backend. It
serializes exactly like the networked backends do, so a value that cannot cross
the wire fails in tests rather than in production.

`NullCacheService` turns caching off without any call site knowing.
"""

import threading
import time
import typing as t

from .contracts import CacheService
from .helpers import dep_token, dep_tokens, expires_at, table_invalidation_tokens, table_invalidation_tokens_many
from .types import TTL, DepSet, GidDep

LOCK_WAIT_SECONDS = 30.0


class MemoryCacheService(CacheService):
    """Keep cache entries and their dependency index in this process only.

    Nothing here is shared between workers, so it is a development and testing
    backend rather than a deployment one.
    """

    def __init__(self) -> None:
        """Start with an empty store, index and lock table."""
        self._entries: dict[str, tuple[bytes, float | None]] = {}
        self._by_dep: dict[str, set[str]] = {}
        self._deps_of: dict[str, set[str]] = {}
        self._locks: set[str] = set()
        self._guard = threading.Lock()
        self._lock_changed = threading.Condition(self._guard)

    def load_entry(self, key: str) -> tuple[bool, bytes | None]:
        """Return a stored payload, dropping it first when it has expired."""
        with self._guard:
            entry = self._entries.get(key)
            if entry is None:
                return False, None

            payload, deadline = entry
            if deadline is not None and time.monotonic() >= deadline:
                self._forget(key)
                return False, None

            return True, payload

    def store_entry(self, key: str, payload: bytes, deps: DepSet, ttl: TTL) -> None:
        """Store a payload and index it under every dependency it recorded."""
        with self._guard:
            self._forget(key)
            self._entries[key] = (payload, expires_at(ttl))
            self._deps_of[key] = dep_tokens(deps)
            for dep in self._deps_of[key]:
                self._by_dep.setdefault(dep, set()).add(key)

    def drop_by_gid(self, gid: str) -> int:
        """Drop every entry that recorded this gid as a dependency."""
        with self._guard:
            keys = list(self._by_dep.get(dep_token(GidDep(gid)), ()))
            for key in keys:
                self._forget(key)
            return len(keys)

    def drop_by_table(self, table: str, gid: str | None = None) -> int:
        """Drop indexed table queries and the requested entity dependencies."""
        return self._drop_tokens(table_invalidation_tokens(table, gid=gid))

    def drop_by_table_many(self, table: str, gids: t.Collection[str]) -> int:
        """Drop a batch of entity dependencies under one guard."""
        return self._drop_tokens(table_invalidation_tokens_many(table, gids=gids))

    def _drop_tokens(self, tokens: set[str]) -> int:
        """Forget each matching entry once while holding the guard."""
        with self._guard:
            keys: set[str] = set()
            for token in tokens:
                keys.update(self._by_dep.get(token, ()))
            for key in keys:
                self._forget(key)
            return len(keys)

    def drop_all(self) -> int:
        """Drop every entry and the whole dependency index with it."""
        with self._guard:
            count = len(self._entries)
            self._entries.clear()
            self._by_dep.clear()
            self._deps_of.clear()
            return count

    def take_lock(self, key: str, wait: bool = False) -> bool:
        """Take a single-flight lock, optionally waiting for its current owner."""
        with self._lock_changed:
            if wait:
                if not self._lock_changed.wait_for(lambda: key not in self._locks, timeout=LOCK_WAIT_SECONDS):
                    return False
            elif key in self._locks:
                return False
            self._locks.add(key)
            return True

    def drop_lock(self, key: str) -> None:
        """Release a single-flight lock."""
        with self._lock_changed:
            self._locks.discard(key)
            self._lock_changed.notify_all()

    def _forget(self, key: str) -> None:
        """Remove one entry and its index entries. Call while holding the guard."""
        self._entries.pop(key, None)
        for dep in self._deps_of.pop(key, set()):
            keys = self._by_dep.get(dep)
            if keys is None:
                continue
            keys.discard(key)
            if not keys:
                del self._by_dep[dep]


class NullCacheService(CacheService):
    """Answer every lookup with a miss and throw every write away.

    Useful for turning caching off in an environment without touching any call
    site, and for proving in a test that a code path is correct uncached.
    """

    def load_entry(self, key: str) -> tuple[bool, bytes | None]:
        """Report a miss for every key."""
        return False, None

    def store_entry(self, key: str, payload: bytes, deps: DepSet, ttl: TTL) -> None:
        """Discard the value."""

    def drop_by_gid(self, gid: str) -> int:
        """Report that nothing was dropped, because nothing was kept."""
        return 0

    def drop_all(self) -> int:
        """Report that nothing was dropped, because nothing was kept."""
        return 0

    def drop_by_table(self, table: str, gid: str | None = None) -> int:
        """No entries are kept in this backend."""
        return 0

    def drop_by_table_many(self, table: str, gids: t.Collection[str]) -> int:
        """No entries are kept in this backend."""
        return 0
