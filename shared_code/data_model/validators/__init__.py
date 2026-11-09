"""Contains utility functions for data validation against database table schemas."""

from typedal import TypedTable
from typedal.types import Table

from shared_code.data_model import AnyDict

__all__ = [
    "validate_fields",
]


def validate_fields(table: Table | type[TypedTable], payload: AnyDict) -> tuple[dict[str, str], AnyDict]:
    """Validates the fields of a payload against the schema of a given table.

    Returns a tuple containing a dictionary of validation errors keyed by field name,
            and a dictionary of validated field values ready to be written.
    """
    return table._validate_fields(payload)
