"""Persisted configuration for public catalogue filters."""

from pydal.validators import IS_IN_SET
from typedal import TypedField

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
        requires=IS_IN_SET({"product": "Product", "method": "Methode", "both": "Beide"}),
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
