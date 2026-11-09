"""Field-visibility helpers for grid and form rendering."""

from typedal import TypedField, TypedTable
from typedal.types import Field, Table


def show(table: Table | type[TypedTable], *fields_to_show: str | Field | TypedField) -> None:
    """Hide every field of `table` except the ones listed.

    A whitelist, so a table gaining a column does not silently gain a form input. Fields left
    out are set `readable=False` *and* `writable=False`: merely clearing `writable` makes
    py4web render them as disabled controls instead of dropping them.

    Note this mutates the shared model definition, so it holds until another route sets its own
    visibility. Every route that cares should therefore declare its full set, which is what
    calling this does.

    :param table: the table being rendered
    :param fields_to_show: the fields that should stay visible
    """
    all_fields = [field.name for field in table]
    field_names = {str(getattr(field, "name", field)) for field in fields_to_show}

    for field in all_fields:
        if field not in field_names:
            table[field].readable = False
            table[field].writable = False
