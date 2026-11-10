"""Public field-exposure helpers."""

import typing as t

from typedal import TypedTable
from typedal.tables import TypedRow
from typedal.types import Field

from shared_code.data_model.constants import INTERNAL_FIELD_NAMES


def is_public_readable_field(table: type[TypedTable], name: str) -> bool:
    """Return whether a model field may be exposed in public catalogue payloads.

    PyDAL retains custom field attributes, so models may set ``public=False``
    without changing the field's admin-form ``readable`` setting.
    """
    field = table[name]
    if (public := getattr(field, "public", None)) is not None:
        # explicitly set to True or False, honor:
        return public

    return name not in INTERNAL_FIELD_NAMES and not name.endswith("_gid")


def public_readable_fields(table: type[TypedTable]) -> list[Field]:
    """Return pydal Field expressions that may be selected for public catalogue rows."""
    return [table[name] for name in table.fields if is_public_readable_field(table, name)]


def public_readable_values[T](row: TypedRow, table: type[TypedTable]) -> T:
    """Return the public field values selected for a catalogue record."""
    return t.cast(T, {name: row[name] for name in table.fields if is_public_readable_field(table, name)})
