"""Method table definitions."""

import typing as t

from pydal.validators import IS_FLOAT_IN_RANGE, IS_NULL_OR
from typedal import QueryBuilder, Ref, TypedField, relationship
from typedal.types import Query

from shared_code.data_model.mixins.search import SearchMixin
from shared_code.data_model.tables.base import BaseTable
from shared_code.data_model.tables.shared_product import SharedProductField

if t.TYPE_CHECKING:
    from shared_code.data_model.tables import Product, Supplier  # noqa: F401


class MethodEd(BaseTable, SharedProductField):
    """Effective-dated method source table."""

    name = TypedField(str, label="Methode Naam")
    guide_price = TypedField(float, label="Richtprijs", requires=IS_NULL_OR(IS_FLOAT_IN_RANGE()))
    sample_copies = TypedField(str, label="Inkijkexemplaren")
    preview_digital_environment = TypedField(str, label="Preview Digitale Omgeving")


class Method(MethodEd, SearchMixin, search_fields=("name", "olid")):
    """Current method model view."""

    products = relationship(
        list["Product"], condition=lambda method, product: product.method_gid == method.gid, join="left"
    )

    supplier = relationship(
        Ref["Supplier"],
        condition=lambda method, supplier: method.supplier_gid == supplier.gid,
        join="inner",
    )

    @classmethod
    def apply_search(cls, search: str, builder: QueryBuilder[t.Self]) -> QueryBuilder[t.Self]:
        """Apply text search, including related supplier matches via SearchMixin."""
        from shared_code.data_model.tables.supplier import Supplier

        def extra_conditions(part: str) -> list[Query]:
            search_part = (part or "").strip()
            if not search_part:
                return []

            supplier_gids = Supplier.apply_search(
                search_part,
                Supplier.select(Supplier.gid),
            ).to_sql()

            return [cls.supplier_gid.belongs(supplier_gids)]

        return cls._apply_search(search, builder, extra_conditions_fn=extra_conditions)
