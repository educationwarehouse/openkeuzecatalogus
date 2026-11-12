"""Shared helpers for constructing DAL queries."""

import typing as t

from typedal import TypedField
from typedal.types import Field, Query

if t.TYPE_CHECKING:
    from pydal.base import DALBase as DAL
else:
    from pydal import DAL


def falsey_query(field_or_db: Field | TypedField[t.Any] | DAL) -> Query:
    """Return an always-false query to build OR conditions from."""
    db = field_or_db if isinstance(field_or_db, DAL) else field_or_db.db
    return Query(db, "FALSE")
