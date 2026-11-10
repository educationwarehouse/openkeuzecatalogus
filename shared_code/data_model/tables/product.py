"""Product table definitions."""

import datetime as dt
import typing as t

from pydal.validators import IS_FLOAT_IN_RANGE, IS_IN_SET, IS_NULL_OR
from typedal import Ref, relationship
from typedal.fields import TypedField
from typedal.helpers import classproperty

from shared_code.data_model.constants import PRODUCT_COMPOSITION_LABELS
from shared_code.data_model.fields import OptionalUUIDField, UUIDReferenceField
from shared_code.data_model.mixins.search import RankedSearchMixin
from shared_code.data_model.representers import comma_separated, dutch_currency, product_composition
from shared_code.data_model.tables.base import EffdtTable
from shared_code.data_model.tables.shared_product import SharedProductField

if t.TYPE_CHECKING:
    from shared_code.data_model import Method, Supplier  # noqa F401; used by relationship()


class ProductEd(EffdtTable, SharedProductField):
    """Effective-dated product source table."""

    isbn = TypedField(str, label="ISBN")
    name = TypedField(str, label="Product Naam")
    method_gid = UUIDReferenceField(label="Methode GID", notnull=True, public=True)
    payment_models = TypedField(list[str], label="Betaalmodellen", represent=comma_separated)
    product_usages = TypedField(list[str], label="Productgebruik", represent=comma_separated)
    related_products = TypedField(list[str], label="Gerelateerde Producten", represent=comma_separated)
    specific_access_urls = TypedField(list[str], label="Specifieke Toegangs-URLs", represent=comma_separated)
    specific_access_url_types = TypedField(list[str], label="Specifieke Toegangs-URL Types", represent=comma_separated)
    level_x_year = TypedField(list[str], label="Niveau x Leerjaar", represent=comma_separated)
    sample_copies_link = TypedField(str, label="Inkijkexemplaren Link")
    recommended_price = TypedField(
        float,
        label="Adviesprijs",
        requires=IS_NULL_OR(IS_FLOAT_IN_RANGE()),
        represent=dutch_currency,
    )
    weight = TypedField(float, label="Gewicht", requires=IS_NULL_OR(IS_FLOAT_IN_RANGE()))
    dimensions = TypedField(str, label="Afmetingen")
    demo_environment_link = TypedField(str, label="Demo Omgeving Link")
    composition = TypedField(str, requires=IS_IN_SET(PRODUCT_COMPOSITION_LABELS), represent=product_composition)
    copyright_type = TypedField(str | None, label="Copyright Type")
    deprecation_date = TypedField(dt.date | None, label="Uitfaseringsdatum")
    end_of_life_date = TypedField(dt.date | None, label="Einde Levensduur")
    follow_up_product = OptionalUUIDField(label="Opvolgend Product")
    for_sale = TypedField(bool | None, label="Te Koop")
    intended_end_user_role = TypedField(str | None, label="Beoogde Eindgebruiker")
    is_consumption_product = TypedField(bool | None, label="Verbruiksproduct")
    sale_unit_size = TypedField(int | None, label="Verkoopeenheid Grootte")
    supported_until_date = TypedField(dt.date | None, label="Ondersteund Tot")

    @classproperty
    def admin_grid(cls) -> str:
        """Return the admin grid identifier for products."""
        return "products"


class Product(ProductEd, RankedSearchMixin, search_fields=("name", "olid")):
    """Current product model view."""

    method = relationship(
        Ref["Method"],
        condition=lambda product, method: product.method_gid == method.gid,
    )

    @property
    def composition_label(self) -> str:
        """Return the localized label for the current composition value."""
        return PRODUCT_COMPOSITION_LABELS.get(self.composition or "", "Product")
