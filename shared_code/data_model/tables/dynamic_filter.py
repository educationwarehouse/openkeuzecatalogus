"""Persisted configuration for public catalogue filters."""

import typing as t

from pydal.validators import IS_EMPTY_OR, IS_IN_SET
from typedal import TypeDAL, TypedField
from typedal.helpers import classproperty
from typedal.types import Validator

from shared_code.data_model.constants import CATALOG_APPLIES_TO_LABELS, INTERNAL_FIELD_NAMES
from shared_code.data_model.tables.base import TableWithGid


class DynamicFilter(TableWithGid):
    """Backend-managed metadata for public product/method filters."""

    slug = TypedField(
        str,
        length=40,
        label="Filter sleutel",
        unique=True,
        comment="Gebruikt in de querystring en als handler-identificatie.",
    )
    label = TypedField(str, length=100, label="Label")
    filter_kind = TypedField(
        str,
        length=20,
        label="Filter type",
        requires=IS_IN_SET(
            {
                "search": "Vrije tekst",
                "dynamic": "Dynamisch veldfilter",
                "custom": "Aangepaste filterhandler",
            }
        ),
        default="dynamic",
    )
    field_name = TypedField(str, length=100, label="Veldnaam")
    match_mode = TypedField(
        str,
        length=10,
        label="Match mode",
        requires=IS_IN_SET({"contains": "Bevat", "belongs": "Is exact"}),
        default="contains",
    )
    applies_to = TypedField(
        str,
        length=10,
        label="Van toepassing op",
        requires=IS_IN_SET(CATALOG_APPLIES_TO_LABELS),
        default="both",
    )
    handler_key = TypedField(str, length=50, label="Handler sleutel")
    widget_kind = TypedField(
        str,
        length=20,
        label="Widget type",
        requires=IS_IN_SET(
            {
                "search": "Zoekveld",
                "select": "Keuzelijst",
                "checkbox": "Checkbox",
            }
        ),
    )
    is_active = TypedField(bool, label="Actief", default=True)
    sort_order = TypedField(int, label="Sortering", default=0)

    @classmethod
    def __on_define__(cls, db: TypeDAL) -> None:
        """Configure field choices after catalogue tables have been defined."""
        super().__on_define__(db)

        from shared_code.data_model.tables.method import Method
        from shared_code.data_model.tables.product import Product

        field_names = (set(Method.fields) | set(Product.fields)) - INTERNAL_FIELD_NAMES

        requires = [IS_EMPTY_OR(IS_IN_SET(sorted(field_names)))]

        cls.field_name.requires = t.cast(list[Validator], requires)

    @classproperty
    def admin_grid(cls) -> str:
        """Return the admin grid identifier for dynamic filters."""
        return "dynamic-filters"
