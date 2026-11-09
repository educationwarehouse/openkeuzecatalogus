"""Invalidate catalogue dependencies directly through public write callbacks."""

import typing as t

from typedal.types import OpRow, Reference, Set

from .contracts import CacheService

if t.TYPE_CHECKING:
    from typedal import TypedTable

    from shared_code.infra.database import DatabaseContext


def invalidate_cache(
    db: DatabaseContext, table: str, gid: str | None = None, caching: CacheService | None = None
) -> int:
    """Invalidate bulk/raw-SQL effects with no database lifecycle overrides."""
    if caching is None:
        caching = db.caching
    return caching.invalidate_table(table, gid=gid)


def install_write_invalidation(model: type[TypedTable], caching: CacheService) -> None:
    """Bind one business model to the supplied cache service."""
    table = model._table
    if table is None:
        raise ValueError(f"Define {model.__name__} before installing cache invalidation")
    table_name = str(table)

    # TODO: Prevent stale cache refill across concurrent writes and commits.
    # Redis invalidates immediately; PostgreSQL deletion shares the write's
    # transaction. Keep finite TTLs until the planned stronger invalidation.
    def inserted(row: OpRow, record_id: Reference) -> None:
        # A new gid still invalidates table queries, including empty listings.
        # Effective-dated edits insert a version of an existing gid as well.
        gid = row.get("gid")
        caching.invalidate_table(table_name, gid=str(gid) if gid else None)

    def changing(dbset: Set) -> bool:
        if "gid" in table.fields:
            gids = [str(gid) for gid in dbset.select(table.gid).column(table.gid)]
            caching.invalidate_table_many(table_name, gids=gids)
        else:
            caching.invalidate_table(table_name)
        return False

    def updating(dbset: Set, row: OpRow) -> bool:
        return changing(dbset)

    model.after_insert(inserted)
    model.before_update(updating)
    model.before_delete(changing)
