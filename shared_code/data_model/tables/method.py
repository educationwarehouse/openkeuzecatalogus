"""Method table definitions."""

import typing as t

from pydal.validators import IS_FLOAT_IN_RANGE, IS_NULL_OR
from typedal import Ref, TypedField, relationship
from typedal.helpers import classproperty

from shared_code.data_model.mixins.search import RankedSearchMixin
from shared_code.data_model.representers import dutch_currency
from shared_code.data_model.tables.base import EffdtTable
from shared_code.data_model.tables.shared_product import SharedProductField

if t.TYPE_CHECKING:
    from shared_code.data_model.tables import Product, Supplier  # noqa: F401


class MethodEd(EffdtTable, SharedProductField):
    """Effective-dated method source table."""

    name = TypedField(str, label="Methode Naam")
    guide_price = TypedField(
        float,
        label="Richtprijs",
        requires=IS_NULL_OR(IS_FLOAT_IN_RANGE()),
        represent=dutch_currency,
    )
    sample_copies = TypedField(str, label="Inkijkexemplaren")
    preview_digital_environment = TypedField(str, label="Preview Digitale Omgeving")

    @classproperty
    def admin_grid(cls) -> str:
        """Return the admin grid identifier for methods."""
        return "methods"


class Method(MethodEd, RankedSearchMixin, search_fields=("name", "olid")):
    """Current method model view."""

    products = relationship(
        list["Product"], condition=lambda method, product: product.method_gid == method.gid, join="left"
    )

    supplier = relationship(
        Ref["Supplier"],
        condition=lambda method, supplier: method.supplier_gid == supplier.gid,
        join="inner",
    )
