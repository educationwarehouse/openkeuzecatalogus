"""The machinery a cache block runs: dependency recording and the block itself."""

import contextlib
import typing as t

from typedal import TypedRows, TypedTable
from typedal.types import Field, Rows

from .helpers import cache_table_name, is_uuid_field, read_field, table_name_of
from .types import TTL, DepSet, GidDep, RowDep, TableDep

if t.TYPE_CHECKING:
    from typedal import QueryBuilder

    from shared_code.infra.database import DatabaseContext

    from .contracts import CacheService


class DependencyRecorder:
    """Collect the entities touched while installed on a TypeDAL database.

    Installing appends hooks to `db._after_collect` and `db._after_execute`;
    leaving removes them. Both are plain lists on a shared `db`, so this is only
    safe while one worker serves one request at a time. That holds today because
    py4web runs under bjoern, which is single-threaded per process. Revisit if
    the server gains threads, or if anything here starts using TypeDAL's async
    workers, which run queries on a thread pool.
    """

    def __init__(self, db: DatabaseContext) -> None:
        """Start an empty recorder bound to a database."""
        self.db = db
        self.deps: DepSet = set()
        self._installed = False

    def seed(self, *args: t.Any) -> None:
        """Record dependencies for records handed to the block directly.

        Without this, caching around already-loaded rows would track nothing:
        a block only sees the queries that run inside it.
        """
        for arg in args:
            if isinstance(arg, TypedRows):
                for row in arg:
                    self._add_record(row)
            elif isinstance(arg, TypedTable):
                self._add_record(arg)

    def _add_record(self, row: TypedTable) -> None:
        if gid := getattr(row, "gid", None):
            self.deps.add(GidDep(gid))
            self.deps.add(TableDep(cache_table_name(table_name_of(row)), gid=str(gid)))
        if (idx := getattr(row, "id", None)) is not None:
            self.deps.add(RowDep(table_name_of(row), int(idx)))

    def harvest(self, rows: Rows) -> None:
        """Walk one raw result set and record what it depended on.

        Runs over rows already in memory, so it costs no extra query.
        Over-tracking is intentional: a dependency that did not influence the
        output only causes an invalidation that was not strictly needed.
        """
        self.deps.update(
            TableDep(cache_table_name(table_name_of(field))) for field in rows.fields if isinstance(field, Field)
        )
        if not rows:
            return

        gid_fields = [field for field in rows.fields if is_uuid_field(field)]
        id_fields = [(field, table_name_of(field)) for field in rows.fields if str(field).endswith(".id")]
        if not gid_fields and not id_fields:
            return

        for row in rows:
            for field in gid_fields:
                if value := read_field(row, field):
                    self.deps.add(GidDep(str(value)))
            for field, table in id_fields:
                if (value := read_field(row, field)) is not None:
                    self.deps.add(RowDep(table, int(t.cast(int, value))))

    def on_execute(self, _builder: QueryBuilder[t.Any], raw: Rows) -> None:
        """Hook body for `db._after_execute`."""
        self.deps.add(TableDep(cache_table_name(str(_builder.model._table))))
        tables = self.db._adapter.tables(_builder.query, *_builder.select_args)
        self.deps.update(TableDep(cache_table_name(str(table).split(" AS ")[0])) for table in tables.values())
        self.harvest(raw)

    def on_collect(self, _builder: QueryBuilder[t.Any], _typed: TypedRows[t.Any], raw: Rows) -> None:
        """Hook body for `db._after_collect`."""
        self.harvest(raw)

    def __enter__(self) -> t.Self:
        """Install the collect and execute hooks for the duration of the block."""
        if self._installed:
            return self

        self.db._after_execute.append(self.on_execute)
        self.db._after_collect.append(self.on_collect)
        self._installed = True
        return self

    def __exit__(self, *_: t.Any) -> None:
        """Remove the hooks again, whether or not the block succeeded."""
        if not self._installed:
            return
        with contextlib.suppress(ValueError):
            self.db._after_execute.remove(self.on_execute)
        with contextlib.suppress(ValueError):
            self.db._after_collect.remove(self.on_collect)
        self._installed = False


class CacheBlock:
    """The object a `with service(...)` block yields.

    `valid` rather than `hit`: an entry can be present but expired, or stored by
    a build whose return shape no longer applies, and neither of those is usable.
    """

    def __init__(
        self,
        service: CacheService,
        key: str,
        recorder: DependencyRecorder,
        ttl: TTL = None,
        lock: bool = False,
    ) -> None:
        """Prepare a block; nothing is looked up until it is entered."""
        self.service = service
        self.key = key
        self.recorder = recorder
        self.ttl = ttl
        self.lock = lock
        self._valid = False
        self._value: t.Any = None
        self._lock_held = False

    @property
    def valid(self) -> bool:
        """Return whether a usable value was found for this key."""
        return self._valid

    @property
    def value(self) -> t.Any:
        """Return the cached value; meaningless unless `valid` is True."""
        return self._value

    @property
    def deps(self) -> DepSet:
        """Return the dependencies recorded so far."""
        return self.recorder.deps

    def set[T](self, value: T) -> T:
        """Store a freshly computed value with everything the block recorded, and return it.

        The only write path. A block that returns without calling this caches
        nothing, which is how one branch of a call site opts out.
        """
        self.service.write(self.key, value, set(self.recorder.deps), self.ttl)
        self._value = value
        return value

    def update_deps(self, *deps: GidDep | RowDep | TableDep) -> None:
        """Declare dependencies for inputs read outside this cache block."""
        self.recorder.deps.update(deps)

    def __enter__(self) -> t.Self:
        """Look the key up, and start recording if nothing usable was found."""
        if self._lookup():
            return self

        if self.lock:
            taken = self.service.guarded("lock", lambda: self.service.take_lock(self.key, wait=True), None)
            self._lock_held = taken is True
            if taken is not None and self._lookup():
                return self

        self.recorder.__enter__()
        return self

    def _lookup(self) -> bool:
        found, value = self.service.read(self.key)
        if found:
            self._valid = True
            self._value = value
        return found

    def __exit__(self, *exc: t.Any) -> None:
        """Stop recording and release the lock, if one was taken."""
        if not self._valid:
            self.recorder.__exit__(*exc)
        if self._lock_held:
            self.service.guarded("unlock", lambda: self.service.drop_lock(self.key), None)
            self._lock_held = False
