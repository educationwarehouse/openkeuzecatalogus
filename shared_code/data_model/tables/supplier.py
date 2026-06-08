"""Supplier table definitions."""

from pydal.validators import IS_IN_SET
from typedal.fields import TypedField

from shared_code.data_model.mixins.effdt import EffdtFields
from shared_code.data_model.tables.base import BaseTable


class Supplier(BaseTable, EffdtFields):
    """Current supplier model view."""

    name = TypedField(str, label="Naam")
    logo_url = TypedField(str, label="Logo URL")
    olid = TypedField(str, label="OLID", unique=True)
    status_visions = TypedField(
        str,
        label="Status Visies",
        requires=IS_IN_SET(
            {
                "nog niet gedeeld",
                "wil niet delen",
                "in gesprek",
                "compleet",
            }
        ),
    )


class SupplierEd(Supplier):
    """Effective-dated supplier source table."""
