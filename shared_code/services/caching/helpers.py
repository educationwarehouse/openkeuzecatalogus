"""Pure helpers behind the cache: key construction, ttl maths and row reading."""

import datetime as dt
import hashlib
import os
import time
import typing as t
from datetime import timedelta

from typedal import TypedRows, TypedTable
from typedal.types import Field, Row

from .types import PUBLIC_SCOPE, TTL, Dep, DepSet, GidDep, RowDep, Scope, TableDep

BUILD_ID_VAR = "SCHEMA_VERSION"
DEFAULT_BUILD_ID = "dev"


def cache_table_name(table: str) -> str:
    """Use the same dependency name for effective-dated tables and their views."""
    return table.removesuffix("_model").removesuffix("_ed")


def dep_token(dep: Dep) -> str:
    """Encode a dependency consistently for indexed cache backends."""
    match dep:
        case GidDep(gid=gid):
            return f"g{gid}"
        case RowDep(table=table, id=idx):
            return f"r{table}/{idx}"
        case TableDep(table=table, gid=None):
            return f"t{cache_table_name(table)}"
        case TableDep(table=table, gid=gid):
            return f"e{cache_table_name(table)}/{gid}"
    raise TypeError(f"Unsupported dependency: {dep!r}")


def dep_tokens(deps: DepSet) -> set[str]:
    """Index exact dependencies and whole-table membership separately."""
    tokens = {dep_token(dep) for dep in deps}
    tokens.update(f"a{cache_table_name(dep.table)}" for dep in deps if isinstance(dep, (RowDep, TableDep)))
    return tokens


def table_invalidation_tokens(table: str, gid: str | None = None) -> set[str]:
    """Find table queries plus one entity, or every dependency in a table."""
    table = cache_table_name(table)
    if gid is None:
        return {f"a{table}"}
    return {dep_token(TableDep(table)), dep_token(TableDep(table, gid=gid)), dep_token(GidDep(gid))}


def table_invalidation_tokens_many(table: str, gids: t.Collection[str]) -> set[str]:
    """Combine entity and query dependencies for one bulk invalidation."""
    tokens: set[str] = set()
    for gid in gids:
        tokens.update(table_invalidation_tokens(table, gid=gid))
    return tokens


def ttl_seconds(ttl: TTL) -> float | None:
    """Turn a ttl into seconds, or None when the entry should not expire on its own."""
    if ttl is None:
        return None
    elif isinstance(ttl, timedelta):
        return ttl.total_seconds()
    else:
        return float(ttl)


def expires_at(ttl: TTL, now: float | None = None) -> float | None:
    """Turn a ttl into a monotonic deadline, or None when the entry never expires."""
    seconds = ttl_seconds(ttl)
    if seconds is None:
        return None
    return (time.monotonic() if now is None else now) + seconds


def deadline(ttl: TTL, now: dt.datetime) -> dt.datetime | None:
    """Turn a ttl into an absolute timestamp, or None when the entry never expires."""
    seconds = ttl_seconds(ttl)
    return None if seconds is None else now + dt.timedelta(seconds=seconds)


def build_id() -> str:
    """Return the identifier separating one deployment's entries from the next.

    Folded into every cache key, so a release cannot be served entries shaped
    by an earlier one. Reuses `SCHEMA_VERSION`, which `edwh setup` already
    stamps; the fallback only applies to a local checkout without it.
    """
    return os.environ.get(BUILD_ID_VAR) or DEFAULT_BUILD_ID


def scope_key(scope: Scope) -> str:
    """Reduce a scope to the stable string that goes into the cache key.

    `None` means public. An anonymous actor collapses onto that same public
    scope: logged-out visitors all see the same thing, so one entry serves them.
    """
    if scope is None:
        return PUBLIC_SCOPE
    elif isinstance(scope, str):
        return scope
    elif scope.kind == "anonymous":
        return PUBLIC_SCOPE
    else:
        return f"{scope.kind}:{scope.id}"


def stringify(value: t.Any) -> str:
    """Render one key component so that equal inputs always produce equal strings.

    Deliberately unconstrained: a call site's arguments are whatever that call
    site varies its result by, and the final branch falls back on `str`.
    """
    if isinstance(value, str):
        return value
    elif isinstance(value, bool):
        return str(int(value))
    elif isinstance(value, TypedTable):
        return f"{table_name_of(value)}:{getattr(value, 'gid', None) or value.id}"
    elif isinstance(value, TypedRows):
        return "[" + ",".join(sorted(stringify(row) for row in value)) + "]"
    elif isinstance(value, t.Mapping):
        pairs = sorted(value.items(), key=lambda item: str(item[0]))
        return "{" + ",".join(f"{key}={stringify(item)}" for key, item in pairs) + "}"
    elif isinstance(value, (set, frozenset)):
        return "[" + ",".join(sorted(stringify(item) for item in value)) + "]"
    elif isinstance(value, (list, tuple)):
        return "[" + ",".join(stringify(item) for item in value) + "]"
    else:
        return str(value)


def build_key(name: str, args: t.Sequence[t.Any], scope: Scope) -> str:
    """Combine the call site's name, arguments, scope and build id into one hashed key."""
    raw = "|".join((build_id(), name, scope_key(scope), *(stringify(arg) for arg in args)))
    return hashlib.sha256(raw.encode()).hexdigest()


def table_name_of(value: Field | TypedTable) -> str:
    """Return the plain table name behind a field or record, dropping any alias."""
    table = getattr(value, "_table", None)
    if table is None:
        return type(value).__name__.lower()
    return str(table).split(" AS ")[0].strip()


def is_uuid_field(field: Field) -> bool:
    """Return whether a field stores a uuid in the database.

    Matches on the database type rather than on a `*_gid` naming convention, so
    a column added later is covered without anyone updating a list.
    """
    return getattr(getattr(field, "type", None), "native", None) == "uuid"


def read_field(row: Row, field: Field) -> t.Any | None:
    """Read one field out of a raw row, tolerating shapes that do not carry it."""
    try:
        return row[field]
    except KeyError, TypeError, AttributeError:
        return None
