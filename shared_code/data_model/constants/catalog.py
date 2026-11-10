"""Catalogue-domain constants."""

import typing as t

CatalogEntityKind = t.Literal["product", "method"]

CATALOG_APPLIES_TO_LABELS = {
    "product": "Product",
    "method": "Methode",
    "both": "Beide",
}
