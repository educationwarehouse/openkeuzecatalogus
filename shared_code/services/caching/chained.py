"""A cache made of several caches, tried in order.

`CACHE_BACKEND=redis,postgres` asks the fast store first and falls back to the
durable one, so a Redis outage costs latency rather than correctness. Writes go
to every member, which is what makes the fallback useful: the slower store
already holds the entry by the time the faster one is unavailable.

Deliberately a fallback rather than a tiered cache. A hit in a later member is
not copied back into an earlier one, because `load_entry` returns a payload
without the dependencies that came with it, and an entry re-stored without its
dependencies could not be invalidated afterwards.
"""

import logging
import typing as t

from endow import GraphBuilder

from .contracts import CacheService, backend_class, backend_names
from .types import TTL, DepSet

logger = logging.getLogger(__name__)


class ChainedCacheService(CacheService):
    """Delegate to several cache backends, preferring the earlier ones."""

    def __init__(self, members: t.Sequence[CacheService]) -> None:
        """Wrap an ordered sequence of backends, fastest first.

        The members are built with their own dependencies before they get here,
        so the chain never has to reach into them afterwards.
        """
        if not members:
            raise ValueError("A chained cache needs at least one backend.")

        self._members = list(members)
        self._lock_holders: dict[str, CacheService] = {}

    @classmethod
    def from_env(cls, builder: GraphBuilder) -> t.Self:
        """Chain every backend `CACHE_BACKEND` names, even when it names only one.

        The base factory collapses a single name onto that backend directly;
        asking for a chain by type gets a chain regardless.
        """
        return cls(builder.build_all([backend_class(name) for name in backend_names()]))

    @property
    def members(self) -> list[CacheService]:
        """Return the backends in the order they are tried."""
        return list(self._members)

    def load_entry(self, key: str) -> tuple[bool, bytes | None]:
        """Return the first hit unless a later backend proves it was invalidated."""
        candidate: bytes | None = None
        found_candidate = False
        for member in self._members:
            try:
                found, payload = member.load_entry(key)
            except Exception as error:
                self._failed(member, "load", error)
                continue

            if not found:
                if found_candidate:
                    return False, None
                continue

            if not found_candidate:
                candidate = payload
                found_candidate = True

        return found_candidate, candidate

    def store_entry(self, key: str, payload: bytes, deps: DepSet, ttl: TTL) -> None:
        """Write to every backend, so any of them can answer later."""
        for member in self._members:
            try:
                member.store_entry(key, payload, deps, ttl)
            except Exception as error:
                self._failed(member, "store", error)

    def drop_by_gid(self, gid: str) -> int:
        """Invalidate in every backend, reporting the largest count.

        Largest rather than the sum: one logical entry usually lives in more
        than one member, and counting it once per member would overstate it.
        """
        dropped = 0
        for member in self._members:
            try:
                dropped = max(dropped, member.drop_by_gid(gid))
            except Exception as error:
                self._failed(member, "invalidate", error)

        return dropped

    def drop_all(self) -> int:
        """Flush every backend, reporting the largest count."""
        dropped = 0
        for member in self._members:
            try:
                dropped = max(dropped, member.drop_all())
            except Exception as error:
                self._failed(member, "invalidate_all", error)

        return dropped

    def drop_by_table(self, table: str, gid: str | None = None) -> int:
        """Invalidate matching dependencies in every member of the chain."""
        dropped = 0
        for member in self._members:
            try:
                dropped = max(dropped, member.drop_by_table(table, gid=gid))
            except Exception as error:
                self._failed(member, "invalidate_table", error)
        return dropped

    def drop_by_table_many(self, table: str, gids: t.Collection[str]) -> int:
        """Invalidate the batch once in each backend."""
        dropped = 0
        for member in self._members:
            try:
                dropped = max(dropped, member.drop_by_table_many(table, gids=gids))
            except Exception as error:
                self._failed(member, "invalidate_table_many", error)
        return dropped

    def take_lock(self, key: str, wait: bool = False) -> bool | None:
        """Take the lock in the first available backend that supports one."""
        for member in self._members:
            try:
                taken = member.take_lock(key, wait=wait)
            except Exception as error:
                self._failed(member, "lock", error)
                continue

            if taken is None:
                continue
            if taken:
                self._lock_holders[key] = member
            return taken

        return None

    def drop_lock(self, key: str) -> None:
        """Release the lock in whichever backend took it."""
        holder = self._lock_holders.pop(key, None)
        if holder is None:
            return

        try:
            holder.drop_lock(key)
        except Exception as error:
            self._failed(holder, "unlock", error)

    @staticmethod
    def _failed(member: CacheService, operation: str, error: Exception) -> None:
        """Note that one member could not do its job, and carry on with the next."""
        logger.warning(
            "cache %s failed on %s: %s: %s",
            operation,
            type(member).__name__,
            type(error).__name__,
            error,
        )
