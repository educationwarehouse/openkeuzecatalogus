"""Effective-dating related fields shared across multiple tables."""

import datetime as dt
import enum
import typing as t

from typedal import TypeDAL as DAL
from typedal import TypedTable
from typedal.types import Query, Table

from shared_code.data_model.constants import EFFECTIVEDATED_UPDATE_EXCLUDED_FIELD_NAMES, AnyDict
from shared_code.util.exceptions import Required
from shared_code.util.time import utcnow

from .table import EffdtTable


def ed_restore_by_id(
    table: type[EffdtTable],
    row_id: str | int,
    last_saved_by: str,
    effdt: dt.datetime | None = None,
) -> dict | None:
    """Restore a historical row by ID and create a new effective-dated row.

    Args:
        table: Effective-dated table to restore into.
        row_id: Row ID of the historical version to restore.
        last_saved_by: User or process that last saved the restored row.
        effdt: optional custom effective date for the restored row (defaults to utcnow)

    Returns:
        The newly inserted row as a dictionary, or `None` if the original row
        does not exist.

    """
    db = table._db
    assert db, "can't continue without db"

    if not (row := table(row_id)):
        return None

    values_to_restore = row.as_dict()

    for column in ("id", "effdt", "effstatus", "sync_gid"):
        values_to_restore.pop(column, None)

    new_id = update_effectivedated(
        db,
        table,
        table.gid == values_to_restore["gid"],
        new_values=values_to_restore,
        effdt=effdt,
        last_saved_by=last_saved_by,
        allow_deleted_update=True,
    )
    db.commit()

    if row := table(new_id):
        row: EffdtTable
        return row.as_dict()
    else:
        return None


def model_to_ed(model: Table | type[TypedTable]) -> type[EffdtTable] | None:
    """Return the matching `_ed` table for a model table, if it exists."""
    db = model._db
    assert db, "can't continue without db"

    ed_name = str(model._rname).removesuffix("_model") + "_ed"

    # try to find typedal cls, fallback to pydal table:
    return db.find_model(ed_name) or db.get(ed_name, None)  # type: ignore


def latest_ed(
    db: DAL,
    table: type[EffdtTable],
    where: Query | bool,
    use_prio: bool = True,
) -> EffdtTable | None:
    """Get the currently-active effective-dated row (including deleted), based on effdt and prio."""
    if use_prio:
        prioed_subselect = db(where)._select(table.prio.max())
        prioed_effdt_subselect = db(where & table.prio.belongs(prioed_subselect))._select(table.effdt.max())
        rows = db(where & table.prio.belongs(prioed_subselect) & table.effdt.belongs(prioed_effdt_subselect)).select(
            table.ALL,
            orderby=~table.effdt,
        )
    else:
        # get the latest row:
        ed_subselect = db(where)._select(table.effdt.max())
        rows = db(where & table.effdt.belongs(ed_subselect)).select(table.ALL, orderby=~table.effdt)

    if len(rows) > 1:
        raise ValueError(f"Multiple rows ({len(rows)}) found for update using {where}")

    return rows.first()


def _normalize_update_values(values: AnyDict | None) -> AnyDict:
    values = values or {}
    return {key: value for key, value in values.items() if key not in EFFECTIVEDATED_UPDATE_EXCLUDED_FIELD_NAMES}


def _normalize_prio(prio: int | bool) -> int | bool:
    if isinstance(prio, enum.Enum):
        return prio.value
    return prio


def _build_update_record(row: EffdtTable | None, effdt: dt.datetime, last_saved_by: str) -> AnyDict:
    record: AnyDict = {}
    if row:
        record.update(row.as_dict())
        # don't overwrite the primary key, this auto-increments
        del record["id"]

    record["effdt"] = effdt
    record.pop("sync_gid", None)
    record["last_saved_by"] = last_saved_by
    return record


def _apply_effstatus_update(
    record: AnyDict,
    values: AnyDict,
    delete: bool,
    allow_deleted_update: bool,
) -> None:
    if delete:
        if values:
            raise ValueError("Cannot delete and update at the same time")
        record["effstatus"] = False
        return

    if record.get("effstatus") is False:
        if allow_deleted_update:
            record["effstatus"] = True
        else:
            raise NotImplementedError("Cannot update a deleted record")


def update_effectivedated(
    db: DAL,
    table: type[EffdtTable],
    where: Query | bool,
    new_values: AnyDict | None = None,
    prio: int | bool = False,  # todo: some enum priorities
    effdt: dt.datetime | None = None,
    last_saved_by: str | type[Required] = Required,
    delete: bool = False,
    allow_deleted_update: bool = False,
) -> int:
    """Update rows in `table` using effective-dated insert semantics.

    If `prio` is not `False`, the new row is based on the most active row and
    may inherit the highest overlapping priority.

    Concurrency note:
        There is a theoretical race condition between reading the latest row
        (`latest_ed`) and inserting the new one. A concurrent request could
        insert a newer row in between, which would be silently superseded.
        This is considered negligible because:
        (a) the window is very narrow (one SELECT + one INSERT),
        (b) effective-dating preserves all history — no data is lost,
        (c) the `sync_gid` column exists and could be used for optimistic
            locking if this ever becomes a real problem, and
        (d) adding database-level locking would be disproportionate overhead
            for the current write patterns.
        If the write volume increases significantly (e.g. bulk imports under
        concurrent load), consider adding a `WHERE effdt = (SELECT max(effdt)
        ...)` guard to detect concurrent updates.

    Args:
        db: Database handle.
        table: Effective-dated table to update.
        where: Filter selecting the target row set.
        new_values: Values to apply on top of the historic row.
        prio: Priority to use, or `False` to disable the priority branch.
        effdt: Effective timestamp; defaults to `utcnow()`.
        last_saved_by: Required user or process identifier.
        delete: When `True`, create a deleted effective-dated row.
        allow_deleted_update: Allow a deleted row to be used as the source
            snapshot for a restore operation.

    Examples:
        >>> update_effectivedated(db, table, query, {"name": "new name"})
        >>> update_effectivedated(db, table, query, {"name": "new name"}, prio=200)
        >>> update_effectivedated(
        ...     db,
        ...     table,
        ...     query,
        ...     {"gid": "new primary key", "name": "new name"},
        ...     prio=200,
        ... )

    """
    if last_saved_by is Required:
        raise Required("last_saved_by is a required argument. ")

    new_values = _normalize_update_values(new_values)

    use_prio = prio is not False

    old_row = latest_ed(db, table, where, use_prio=use_prio)
    record_to_insert = _build_update_record(old_row, effdt or utcnow(), str(last_saved_by))

    if use_prio:
        record_to_insert["prio"] = _normalize_prio(prio)

    _apply_effstatus_update(record_to_insert, new_values, delete, allow_deleted_update)

    # update the old record with the new values parameter
    record_to_insert.update(new_values)
    # insert a new record based on the accumulated values of the old record
    # and the parameters, effdate and optionally priority

    latest = table.insert(**record_to_insert)

    # type of 'latest' depends on typedal/pydal usage.
    return latest if isinstance(latest, int) else latest.id


def validate_and_update_effectivedated[T: TypedTable](
    table: type[T], record: T, **fields: t.Any
) -> tuple[T, None] | tuple[None, dict[str, str]]:
    """Validate fields and persist them through an effective-dated record update."""
    pydal_table = table._ensure_table_defined()
    errors, validated_fields = pydal_table._validate_fields(fields, record=record)
    if errors:
        return None, errors

    return record.update_record(**validated_fields), None
