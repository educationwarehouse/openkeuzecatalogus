"""Product table definitions."""

import typing as t

from pydal.validators import IS_FLOAT_IN_RANGE, IS_IN_SET, IS_NULL_OR
from typedal import Ref, relationship
from typedal.fields import TypedField, UUIDField

from shared_code.data_model.mixins import SearchMixin
from shared_code.data_model.representers import comma_separated
from shared_code.data_model.tables.base import BaseTable, SharedProductField

if t.TYPE_CHECKING:  # pragma: no cover
    from shared_code.data_model import Method, Supplier  # noqa F401; used by relationship()


PRODUCT_COMPOSITION_LABELS = {
    "package": "Productpakket",
    "single": "Los product",
    "component": "Onderdeel (niet los verkrijgbaar)",
}


class Product(BaseTable, SharedProductField, SearchMixin, search_fields=("name", "olid")):
    """Current product model view."""

    isbn = TypedField(str, label="ISBN")
    name = TypedField(str, label="Product Naam")
    method_gid = UUIDField(filter_out=str, label="Methode GID")
    level_x_year = TypedField(list[str], label="Niveau x Leerjaar", represent=comma_separated)
    sample_copies_link = TypedField(str, label="Inkijkexemplaren Link")
    recommended_price = TypedField(float, label="Adviesprijs", requires=IS_NULL_OR(IS_FLOAT_IN_RANGE()))
    weight = TypedField(float, label="Gewicht", requires=IS_NULL_OR(IS_FLOAT_IN_RANGE()))
    dimensions = TypedField(str, label="Afmetingen")
    demo_environment_link = TypedField(str, label="Demo Omgeving Link")
    composition = TypedField(str, requires=IS_IN_SET(("package", "component", "single")))

    method = relationship(
        Ref["Method"],
        condition=lambda product, method: product.method_gid == method.gid,
    )

    @property
    def composition_label(self) -> str:
        """Return the localized label for the current composition value."""
        return PRODUCT_COMPOSITION_LABELS.get(self.composition or "", "Product")


class ProductEd(Product):
    """Effective-dated product source table."""
