"""Public field-exposure helpers."""

import typing as t

from typedal import TypedTable
from typedal.tables import TypedRow

from shared_code.data_model.constants import INTERNAL_FIELD_NAMES


def is_public_readable_field(table: type[TypedTable], name: str) -> bool:
    """Return whether a model field may be exposed in public catalogue payloads.

    .. note::
        Currently only used for template rendering (not internet-facing APIs).
        If this is ever used for a public API, fields like `Supplier.email_domains`
        (used for automatic role assignment) must be explicitly excluded.
        See Odoo task #9155.
    """
    return getattr(table[name], "readable", False) and name not in INTERNAL_FIELD_NAMES and not name.endswith("_gid")


def public_readable_values[T](row: TypedRow, table: type[TypedTable]) -> T:
    """Return the public field values selected for a catalogue record."""
    return t.cast(T, {name: row[name] for name in table.fields if is_public_readable_field(table, name)})
