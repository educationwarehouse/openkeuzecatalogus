"""Public catalogue participation counts and their underlying suppliers."""

import typing as t

from shared_code.data_model import Product, Supplier
from shared_code.data_model.constants.catalog import PARTICIPATION_LABELS
from shared_code.modules.products import ProductBackend


class CatalogueSupplier(t.TypedDict):
    """Public supplier identity, without internal import or contact information."""

    gid: str
    name: str


class CatalogueParticipationGroup(t.TypedDict):
    """One mutually exclusive widget segment and its dropdown contents."""

    key: str
    label: str
    count: int
    suppliers: list[CatalogueSupplier]


def catalogue_participation_groups() -> list[CatalogueParticipationGroup]:
    """Prefer actual public products over the manually maintained expectation."""
    available_gids = set(ProductBackend.public_product_query(preselect_public=False).column(Product.supplier_gid))
    groups = {
        key: CatalogueParticipationGroup(key=key, label=label, count=0, suppliers=[])
        for key, label in (
            ("available", "Beschikbaar"),
            ("soon", PARTICIPATION_LABELS["soon"]),
            ("in_conversation", PARTICIPATION_LABELS["in_conversation"]),
        )
    }

    for supplier in Supplier.select(Supplier.gid, Supplier.name, Supplier.catalogue_participation_status).collect():
        key = "available" if supplier.gid in available_gids else supplier.catalogue_participation_status

        if key in groups:
            groups[key]["suppliers"].append({"gid": str(supplier.gid), "name": supplier.name})

    for group in groups.values():
        group["suppliers"].sort(key=lambda supplier: supplier["name"].casefold())
        group["count"] = len(group["suppliers"])

    return list(groups.values())
