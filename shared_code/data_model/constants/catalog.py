"""Catalogue-domain constants."""

import typing as t

CatalogEntityKind = t.Literal["product", "method"]
CatalogListingKind = t.Literal["product", "method", "package"]

CATALOG_APPLIES_TO_LABELS = {
    "product": "Product",
    "method": "Methode",
    "package": "Pakket",
    "both": "Producten en methodes",
}

PARTICIPATION_LABELS = {
    "unknown": "Geen toezegging bekend",
    "participating": "Doet mee, data gedeeld",
    "soon": "Binnenkort gedeeld",
    "in_conversation": "In gesprek",
}
