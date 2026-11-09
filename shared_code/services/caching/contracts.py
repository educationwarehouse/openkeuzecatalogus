"""The cache service contract.

The storage layer is deliberately absent: everything here works in terms of a
key, a payload and a set of `Dep` objects. Concrete backends decide how those
are encoded, how long they are kept and how much they are willing to hold.
"""

import abc
import logging
import os
import typing as t

import dill  # nosec: payloads are written by this service only
from endow import GraphBuilder, Service

from .helpers import build_key
from .module import CacheBlock, DependencyRecorder
from .types import TTL, DepSet, Scope

if t.TYPE_CHECKING:
    # at module scope this import cycles: the context imports shared_code.modules.auth,
    # which reaches shared_code.services, whose __init__ imports this package
    from shared_code.infra.database import DatabaseContext

logger = logging.getLogger(__name__)

BACKEND_VAR = "CACHE_BACKEND"
DESERIALIZATION_FAILED = object()


def backend_names() -> list[str]:
    """Return the backends `CACHE_BACKEND` asks for, in the order it gives them."""
    names = [name.strip().lower() for name in os.environ.get(BACKEND_VAR, "none").split(",") if name.strip()]
    return names or ["none"]


def backend_class(name: str) -> type[CacheService]:
    """Look up one backend class by name. Imported lazily, so only the named one loads."""
    match name:
        case "redis":
            from .redis import RedisCacheService

            return RedisCacheService
        case "postgres":
            from .postgres import PostgresCacheService

            return PostgresCacheService
        case "memory":
            from .memory import MemoryCacheService

            return MemoryCacheService
        case "none":
            from .memory import NullCacheService

            return NullCacheService
        case _:
            raise ValueError(f"Unknown {BACKEND_VAR}: {name!r}. Expected 'redis', 'postgres', 'memory' or 'none'.")


class CacheService(Service, abc.ABC):
    """Cache a slow operation and remember which entities it depended on.

    Backends implement storage only. Key construction, dependency recording and
    the block's behaviour live here, so swapping a backend cannot quietly change
    how stale the data may get.
    """

    db: DatabaseContext

    # start contract to be implemented

    @abc.abstractmethod
    def load_entry(self, key: str) -> tuple[bool, bytes | None]:
        """Return `(found, payload)` for a key, treating an expired entry as missing."""
        ...

    @abc.abstractmethod
    def store_entry(self, key: str, payload: bytes, deps: DepSet, ttl: TTL) -> None:
        """Persist a payload and index every dep so an invalidation can find it again."""
        ...

    @abc.abstractmethod
    def drop_by_gid(self, gid: str) -> int:
        """Drop every entry that listed this gid, returning how many went."""
        ...

    @abc.abstractmethod
    def drop_all(self) -> int:
        """Drop everything this service owns, returning how many entries went."""
        ...

    @abc.abstractmethod
    def drop_by_table(self, table: str, gid: str | None = None) -> int:
        """Drop table query entries and one entity, or every entry in the table."""
        ...

    def drop_by_table_many(self, table: str, gids: t.Collection[str]) -> int:
        """Fallback for custom backends without bulk invalidation."""
        return sum(self.drop_by_table(table, gid=gid) for gid in set(gids))

    def take_lock(self, key: str, wait: bool = False) -> bool | None:
        """Take a single-flight lock, optionally waiting; None means unsupported."""
        return None

    def drop_lock(self, key: str) -> None:
        """Release a lock taken by `take_lock`."""

    # end contract

    @classmethod
    def from_env(cls, builder: GraphBuilder) -> CacheService:
        """Resolve `CACHE_BACKEND` into wired backends.

        `"postgres,redis"` -> a `ChainedCacheService` over a `PostgresCacheService`
        and a `RedisCacheService`, each built through the graph so it gets its own
        dependencies. One name gives that backend on its own.

        A concrete subclass builds itself rather than running the dispatcher,
        which would otherwise answer a request for one backend with another.
        """
        if cls is not CacheService:
            return cls()

        members = builder.build_all([backend_class(name) for name in backend_names()])
        if len(members) == 1:
            return members[0]

        from .chained import ChainedCacheService

        return ChainedCacheService(members)

    def __call__(
        self,
        name: str,
        *args: t.Any,
        scope: Scope,
        ttl: TTL = None,
        lock: bool = False,
    ) -> CacheBlock:
        """Open a cache block for one call site.

        `scope` is keyword-only and has no default, so a call site cannot widen
        its audience by omission. Pass the actor for per-user results, a string
        where a role or tenant is the real discriminator, or `None` for public
        data.

        Positional arguments do double duty: they vary the key, and any
        TypedTable or TypedRows among them seeds the dependency set.
        """
        recorder = DependencyRecorder(self.db)
        recorder.seed(*args)
        return CacheBlock(self, build_key(name, args, scope), recorder, ttl=ttl, lock=lock)

    def invalidate(self, gid: str) -> int:
        """Drop every cached entry that depended on one entity."""
        return self.guarded("invalidate", lambda: self.drop_by_gid(gid), 0)

    def invalidate_all(self) -> int:
        """Drop everything this cache holds."""
        return self.guarded("invalidate_all", self.drop_all, 0)

    def invalidate_table(self, table: str, gid: str | None = None) -> int:
        """Invalidate indexed dependencies without knowing the storage backend."""
        return self.guarded("invalidate_table", lambda: self.drop_by_table(table, gid=gid), 0)

    def invalidate_table_many(self, table: str, gids: t.Collection[str]) -> int:
        """Invalidate a batch of entities and their shared query dependencies."""
        if not gids:
            return 0
        return self.guarded("invalidate_table_many", lambda: self.drop_by_table_many(table, gids=gids), 0)

    def read(self, key: str) -> tuple[bool, t.Any]:
        """Load and deserialize one entry, reporting a broken backend as a miss."""
        found, payload = self.guarded("load", lambda: self.load_entry(key), (False, None))
        if not found or payload is None:
            return False, None
        value = self.guarded("deserialize", lambda: self.loads(payload), DESERIALIZATION_FAILED)
        if value is DESERIALIZATION_FAILED:
            return False, None
        return True, value

    def write(self, key: str, value: t.Any, deps: DepSet, ttl: TTL) -> None:
        """Serialize and persist one entry, swallowing a broken backend."""
        self.guarded("store", lambda: self.store_entry(key, self.dumps(value), deps, ttl), None)

    # --- serialization ---

    def dumps(self, value: t.Any) -> bytes:
        """Serialize a value for storage."""
        return dill.dumps(value)

    def loads(self, payload: bytes) -> t.Any:
        """Deserialize a stored payload.

        Only ever reads back what `dumps` wrote into this service's own
        keyspace, so the payload is not untrusted input. It does mean the store
        must stay as trusted as the application itself: anything able to write
        to the cache keyspace can execute code here.
        """
        return dill.loads(payload)  # noqa: S301  # nosec: written by this service

    def guarded[T](self, operation: str, action: t.Callable[[], T], fallback: T) -> T:
        """Run one backend operation, falling back rather than breaking the caller.

        A dead backend costs latency, never correctness, but it should not be
        able to stay dead quietly, hence the warning.
        """
        try:
            return action()
        except Exception as error:
            logger.warning("cache %s failed: %s: %s", operation, type(error).__name__, error)
            return fallback
