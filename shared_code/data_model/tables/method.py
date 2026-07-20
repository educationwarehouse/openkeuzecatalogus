"""Method table definitions."""

import typing as t

from pydal.validators import IS_FLOAT_IN_RANGE, IS_NULL_OR
from typedal import TypedField, relationship

from shared_code.data_model.mixins.search import SearchMixin
from shared_code.data_model.tables.base import BaseTable
from shared_code.data_model.tables.shared_product import SharedProductField

if t.TYPE_CHECKING:
    from shared_code.data_model.tables.product import Product


class Method(BaseTable, SharedProductField, SearchMixin, search_fields=("name", "olid")):
    """Current method model view."""

    name = TypedField(str, label="Methode Naam")
    guide_price = TypedField(float, label="Richtprijs", requires=IS_NULL_OR(IS_FLOAT_IN_RANGE()))
    sample_copies = TypedField(str, label="Inkijkexemplaren")
    preview_digital_environment = TypedField(str, label="Preview Digitale Omgeving")

    products = relationship(
        list["Product"],
        condition=lambda method, product: product.method_gid == method.gid,
    )


class MethodEd(Method):
    """Effective-dated method source table."""
