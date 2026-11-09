"""Helpers for deriving choices from bar-encoded list fields."""

from typedal.fields import TypedField
from typedal.types import Query


def possible_list_values(field: TypedField[list[str]], where: str | Query = "") -> set[str]:
    """Return the distinct non-empty values stored in a list field."""
    db = field._db
    table_name = field.table._rname
    column_name = field._rname

    assert db and table_name and column_name, "can't continue without db/field names"

    and_where = f"AND {where}" if where else ""

    query = f"""
    SELECT DISTINCT TRIM(BOTH '|' FROM value)
    FROM {table_name},
    LATERAL unnest(string_to_array({column_name}, '|')) AS value
    WHERE value <> ''
    {and_where}
    ;
    """  # noqa: S608 - `where` is in our control

    return {_[0] for _ in db.executesql(query)}


__all__ = ["possible_list_values"]
