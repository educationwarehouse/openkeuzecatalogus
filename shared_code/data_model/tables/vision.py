"""Vision table definitions."""

import typing as t

from pydal.validators import IS_IN_DB
from typedal import QueryBuilder, Ref, TypeDAL, relationship
from typedal.fields import TextField, TypedField
from typedal.helpers import classproperty
from typedal.types import Query, Validator

from shared_code.data_model.fields import UUIDReferenceField
from shared_code.data_model.mixins.search import SearchMixin
from shared_code.data_model.tables.base import EffdtTable
from shared_code.data_model.tables.method import Method
from shared_code.data_model.tables.product import Product
from shared_code.data_model.tables.supplier import Supplier


class VisionEd(EffdtTable):
    """Effective-dated vision source table."""

    olid = TypedField(str, label="OLID")
    onderwijskwaliteit = UUIDReferenceField(label="Onderwijskwaliteit", writable=True)
    visie = TextField(label="Visie")
    property_bag = TypedField(object, default=lambda: {}, label="Property Bag")  # noqa: PIE807 - pydal complains if you use default=dict

    @classmethod
    def validate_unique_olid_theme(
        cls,
        olid: str,
        onderwijskwaliteit: str,
        excluding_gid: str | None = None,
    ) -> str | None:
        """Return an error when an OLID already has a Vision for this theme."""
        if not olid or not onderwijskwaliteit:
            return "'olid' en thema moeten beide ingevuld zijn."

        query = (Vision.olid == olid) & (Vision.onderwijskwaliteit == onderwijskwaliteit)
        if excluding_gid:
            query &= Vision.gid != excluding_gid

        return (
            "Er bestaat al een visie voor deze combinatie van 'olid' en thema."
            if Vision.where(query).exists()
            else None
        )

    @classmethod
    def __on_define__(cls, db: TypeDAL) -> None:
        """Offer only current vision-theme definitions in forms."""
        from shared_code.data_model import VisionThemeDefinition

        super().__on_define__(db)
        requires = [
            IS_IN_DB(
                db,
                VisionThemeDefinition.gid,
                "%(title)s",
                orderby=(VisionThemeDefinition.sort_order, VisionThemeDefinition.id),
            )
        ]
        cls.onderwijskwaliteit.requires = t.cast(list[Validator], requires)


class Vision(VisionEd, SearchMixin, search_fields=("olid", "onderwijskwaliteit", "visie")):
    """Current vision model view."""

    @classproperty
    def admin_grid(cls) -> str:
        """Return the admin grid identifier for vision model rows."""
        return "visions"

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

    product = relationship(Ref[Product], condition=lambda vision, product: vision.olid == product.olid, join="left")
    method = relationship(Ref[Method], condition=lambda vision, method: vision.olid == method.olid, join="left")
    supplier = relationship(Ref[Supplier], condition=lambda vision, supplier: vision.olid == supplier.olid, join="left")
