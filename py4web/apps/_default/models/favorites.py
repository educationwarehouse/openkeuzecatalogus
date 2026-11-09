"""Favorite view-model helpers for public catalog routes."""

import typing as t

from typedal.types import Pagination

from shared_code.modules.catalog_filters import CatalogEntityKind
from shared_code.modules.favorites import FavoriteItem

from . import backend
from .settings import FavoriteSettings


class FavoriteActionContext(t.TypedDict):
    """Template context for one favorite action control."""

    entity_kind: CatalogEntityKind
    entity_gid: str
    is_favorite: bool


class FavoriteRowsContext(t.TypedDict):
    """Template context for one favorite tab page."""

    entity_kind: CatalogEntityKind
    items: list[FavoriteItem]
    pagination: Pagination


def favorite_action_context(settings: FavoriteSettings, gid: str) -> FavoriteActionContext:
    """Build the reusable favorite-action template context."""
    return {
        "entity_kind": settings.entity_kind,
        "entity_gid": gid,
        "is_favorite": backend.favorites.is_favorite(settings.entity_kind, gid),
    }


def favorite_rows_context(settings: FavoriteSettings) -> FavoriteRowsContext:
    """Build one paginated favorite-tab template context."""
    rows = backend.favorites.list_favorites(settings.entity_kind, page=settings.page)
    return {
        "entity_kind": settings.entity_kind,
        "items": backend.favorites.describe(rows),
        "pagination": rows.pagination,
    }


def recent_favorites() -> list[FavoriteItem]:
    """Return the profile-adjacent recent favorites."""
    return backend.favorites.list_recent()
