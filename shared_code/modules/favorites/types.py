"""Typed values exposed by the personal favorites domain."""

import dataclasses as dc
import datetime as dt

from shared_code.modules.catalog_filters import CatalogEntityKind


@dc.dataclass(frozen=True)
class FavoriteItem:
    """Display information for one active catalog favorite."""

    favorite_gid: str
    entity_kind: CatalogEntityKind
    entity_gid: str
    name: str
    favorited_at: dt.datetime
    available: bool

    @property
    def entity_label(self) -> str:
        """Return the Dutch display label for the catalog entity type."""
        return "Product" if self.entity_kind == "product" else "Methode"
