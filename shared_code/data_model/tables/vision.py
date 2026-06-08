"""Vision table definitions."""

import typing as t

from pydal.validators import IS_IN_SET
from typedal import QueryBuilder
from typedal.fields import TextField, TypedField
from typedal.types import Query

from shared_code.data_model.constants import THEMES
from shared_code.data_model.mixins import EffdtFields, SearchMixin
from shared_code.data_model.tables.base import BaseTable
from shared_code.data_model.tables.method import Method
from shared_code.data_model.tables.product import Product
from shared_code.data_model.tables.supplier import Supplier


class Vision(BaseTable, EffdtFields, SearchMixin, search_fields=("olid", "onderwijskwaliteit", "visie")):
    """Current vision model view."""

    olid = TypedField(str, label="OLID")
    onderwijskwaliteit = TypedField(
        str,
        label="Onderwijskwaliteit",
        requires=IS_IN_SET(THEMES),
    )
    visie = TextField(label="Visie")
    property_bag = TypedField(object, default=lambda: {}, label="Property Bag")  # noqa: PIE807 - pydal complains if you use default=dict

    @classmethod
    def apply_search(cls, search: str, builder: QueryBuilder[t.Self]) -> QueryBuilder[t.Self]:
        """Apply text search, including supplier/method/product name matches on `olid`."""

        def extra_conditions(part: str) -> list[Query]:
            search_part = (part or "").strip()
            if not search_part:
                return []

            like = f"%{search_part}%"
            supplier_olids = Supplier.where(Supplier.name.ilike(like)).select(Supplier.olid).to_sql()
            method_olids = Method.where(Method.name.ilike(like)).select(Method.olid).to_sql()
            product_olids = Product.where(Product.name.ilike(like)).select(Product.olid).to_sql()

            return [
                cls.olid.belongs(supplier_olids),
                cls.olid.belongs(method_olids),
                cls.olid.belongs(product_olids),
            ]

        return cls._apply_search(search, builder, extra_conditions_fn=extra_conditions)


class VisionEd(Vision):
    """Effective-dated vision source table."""
