"""Persisted configuration for public catalogue sort options."""

from pydal.validators import IS_IN_SET
from typedal import TypedField
from typedal.helpers import classproperty

from shared_code.data_model.constants import CATALOG_APPLIES_TO_LABELS
from shared_code.data_model.tables.base import TableWithGid
from shared_code.data_model.validators.sort_expression import IS_SORT_EXPRESSION


class DynamicSort(TableWithGid):
    """Backend-managed metadata for public product/method sort options."""

    slug = TypedField(
        str,
        length=40,
        label="Sorteer sleutel",
        unique=True,
        comment="Gebruikt in de querystring en als sorteer-identificatie.",
    )
    label = TypedField(str, length=100, label="Label")
    applies_to = TypedField(
        str,
        length=10,
        label="Van toepassing op",
        requires=IS_IN_SET(CATALOG_APPLIES_TO_LABELS),
        default="both",
    )
    order_expression = TypedField(
        str,
        length=255,
        label="Order expressie",
        comment="Bijvoorbeeld 'name', '~name', 'edition, name, id' of 'random'.",
        requires=IS_SORT_EXPRESSION(),
    )

    is_default = TypedField(bool, label="Standaard", default=False)
    is_active = TypedField(bool, label="Actief", default=True)
    sort_order = TypedField(int, label="Sortering", default=0)

    @classproperty
    def admin_grid(cls) -> str:
        """Return the admin grid identifier for dynamic sorts."""
        return "dynamic-sorts"
