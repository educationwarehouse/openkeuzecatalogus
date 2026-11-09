"""Postgres-backed cache service.

Slower than Redis, but it survives a Redis outage and needs no extra
infrastructure, so it makes a sensible second link in a chain
(`CACHE_BACKEND=redis,postgres`).

Its two tables are created by a migration that only exists when this backend is
selected, so an installation that never uses it never gains them.
"""

import datetime as dt
import typing as t

from typedal import TypedField, TypedTable

from .contracts import CacheService
from .helpers import deadline, dep_token, dep_tokens, table_invalidation_tokens, table_invalidation_tokens_many
from .types import TTL, DepSet, GidDep


class CacheEntry(TypedTable):
    """One cached payload, keyed by the hash the contract built."""

    key: TypedField[str]
    payload: TypedField[bytes]
    expires_at: TypedField[dt.datetime | None]


class CacheDependency(TypedTable):
    """One entity a cached payload depended on."""

    entry: TypedField[CacheEntry]
    token: TypedField[str]


class PostgresCacheService(CacheService):
    """Store cache entries and their dependency index in the application database."""

    def __init__(self) -> None:
        """Start out with the cache models still unbound."""
        self._defined = False

    def define_tables(self) -> None:
        """Teach TypeDAL the shape of the tables the migration created, once.

        Deferred until first use because `db` is wired after construction.
        Never migrates: the tables come from `create_cache_tables`, and
        `redefine` keeps a second service on the same connection from tripping
        over "table already defined", whose recovery path would roll the
        caller's uncommitted transaction back.
        """
        # TypedTable bindings are shared across service instances. Another
        # connection may have rebound or closed these models since our last use.
        if self._defined and CacheEntry._db is self.db and CacheDependency._db is self.db:
            return

        self.db.define(CacheEntry, migrate=False, redefine=True)
        self.db.define(CacheDependency, migrate=False, redefine=True)
        self._defined = True

    def load_entry(self, key: str) -> tuple[bool, bytes | None]:
        """Return a stored payload, dropping it first when it has expired."""
        self.define_tables()
        row = CacheEntry.where(CacheEntry.key == key).first()
        if row is None:
            return False, None

        if row.expires_at is not None and row.expires_at <= self._now():
            self._forget(key)
            return False, None

        # TypedField's descriptor types class and instance access as one union,
        # so ty reveals `bytes | TypedField[bytes]` rather than plain bytes
        return True, t.cast(bytes, row.payload)

    def store_entry(self, key: str, payload: bytes, deps: DepSet, ttl: TTL) -> None:
        """Write a payload and index it under every dependency it recorded."""
        self.define_tables()
        expires_at = deadline(ttl, now=self._now())
        if expires_at is not None and expires_at <= self._now():
            # already expired on arrival; storing it would only serve stale data
            self._forget(key)
            return

        entry = CacheEntry.upsert({"key": key}, payload=payload, expires_at=expires_at)
        CacheDependency.where(CacheDependency.entry == entry.id).delete()
        if deps:
            CacheDependency.bulk_insert([{"entry": entry, "token": token} for token in dep_tokens(deps)])

    def drop_by_gid(self, gid: str) -> int:
        """Drop every entry that recorded this gid.

        The dependency rows go with them: the foreign key is ON DELETE CASCADE.
        """
        self.define_tables()
        token = dep_token(GidDep(gid))
        entries = CacheDependency.where(CacheDependency.token == token).select(CacheDependency.entry).to_sql()
        return len(CacheEntry.where(CacheEntry.id.belongs(entries)).delete())

    def drop_all(self) -> int:
        """Drop every entry this cache owns, cascading to its dependency rows."""
        self.define_tables()
        return len(CacheEntry.where(CacheEntry.id > 0).delete())

    def drop_by_table(self, table: str, gid: str | None = None) -> int:
        """Drop only entries indexed under the changed table or entity."""
        return self._drop_tokens(table_invalidation_tokens(table, gid=gid))

    def drop_by_table_many(self, table: str, gids: t.Collection[str]) -> int:
        """Delete a batch of dependencies through one subquery."""
        return self._drop_tokens(table_invalidation_tokens_many(table, gids=gids))

    def _drop_tokens(self, tokens: set[str]) -> int:
        """Delete indexed entries without materializing dependency IDs."""
        if not tokens:
            return 0
        self.define_tables()
        entries = CacheDependency.where(CacheDependency.token.belongs(tokens)).select(CacheDependency.entry).to_sql()
        return len(CacheEntry.where(CacheEntry.id.belongs(entries)).delete())

    # Locking is left to a faster member of the chain: a session-scoped advisory
    # lock does not survive pydal's connection pooling cleanly, and a lock table
    # would need its own expiry sweeper to be safe after a worker dies.

    @staticmethod
    def _now() -> dt.datetime:
        """Return the naive UTC timestamp the timestamp column stores."""
        from shared_code.util.time import utcnow

        return utcnow().replace(tzinfo=None)

    def _forget(self, key: str) -> None:
        """Remove one entry, cascading to the dependency rows pointing at it."""
        CacheEntry.where(CacheEntry.key == key).delete()
