"""Overlap matching for `list:` columns, shared by catalogue-style queries."""

import typing as t

from typedal import TypedField
from typedal.types import Field, Query

from shared_code.util.queries import falsey_query
from shared_code.util.types import MultiValue


def any_value_matches(field: Field | TypedField[t.Any], values: MultiValue[str]) -> Query | None:
    """Match rows whose `list:` column shares at least one value with `values`.

    pydal stores `list[str]` as a delimited text column, so membership is a substring test per
    value, OR-ed together. This is the same shape `CatalogFieldFilterDefinition.apply` builds for
    dynamic filters (`definitions.py:336-341`); it lives here so queries that are not driven by a
    `DynamicFilter` record can match the catalogue's behaviour exactly.

    Returns None when there is nothing to match on, so callers can distinguish "no constraint"
    from "a constraint that excludes everything" and decide which they want.
    """
    # clean values:
    values = [value for value in values if value]
    if not values:
        return None

    # start off with falsey query so we can do |=
    query = falsey_query(field)
    for value in values:
        query |= field.contains(value)

    return query


__all__ = ["any_value_matches"]
