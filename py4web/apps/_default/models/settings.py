"""Typed request settings for public catalog and favorites routes."""

import typing as t

from common.fixtures import SettingsFixture
from common.models.request_data import CatalogView, parse_form_data

from py4web import HTTP, request
from shared_code.data_model import AnyDict, CatalogFavorite, Method, Product
from shared_code.modules.catalog_filters import CatalogEntityKind, ResolvedCatalogFilters

from . import backend


class CatalogSettingsBase:
    """Normalize public catalog pagination, display, sorting, and filter input."""

    entity_kind: CatalogEntityKind
    page: int = 1
    view: CatalogView = "list"
    sort: str = ""
    filters: AnyDict | None = None

    def normalize_catalog_request(self, setting_keys: t.Iterable[str]) -> None:
        """Retain request values that are not declared catalog settings as filters."""
        filters = parse_form_data(request)
        for key in setting_keys:
            filters.pop(key, None)
        self.filters = filters
        if self.page < 1:
            raise HTTP(400, "Ongeldige waarde voor 'page'")

    @property
    def page_limit(self) -> int:
        """Return the page size for the selected catalogue display mode."""
        return 50 if self.view == "list" else 12

    def selected_sort(self, resolved_filters: ResolvedCatalogFilters) -> str:
        """Return the requested sort, falling back to the first available option."""
        return self.sort or next(iter(resolved_filters.sort_options), "")


class ProductCatalogSettings(CatalogSettingsBase, SettingsFixture[Product]):
    """Catalog request settings for product routes."""

    entity_kind: CatalogEntityKind = "product"

    def on_request(self, context: dict[str, t.Any]) -> None:
        """Parse product settings before preserving its catalog filters."""
        SettingsFixture.on_request(self, context)
        self.normalize_catalog_request(self.setting_annotations())

    def resolved_filters(self) -> ResolvedCatalogFilters:
        """Resolve the current request's public product filters."""
        return backend.products.resolve_public_product_filters(self.filters)


class MethodCatalogSettings(CatalogSettingsBase, SettingsFixture[Method]):
    """Catalog request settings for method routes."""

    entity_kind: CatalogEntityKind = "method"

    def on_request(self, context: dict[str, t.Any]) -> None:
        """Parse method settings before preserving its catalog filters."""
        SettingsFixture.on_request(self, context)
        self.normalize_catalog_request(self.setting_annotations())

    def resolved_filters(self) -> ResolvedCatalogFilters:
        """Resolve the current request's public method filters."""
        return backend.methods.resolve_public_method_filters(self.filters)


class FavoriteSettings:
    """Normalize favorite-page and favorite-mutation request input."""

    entity_kind: CatalogEntityKind
    page: int = 1
    active: bool | None = None

    def validate_page(self) -> None:
        """Reject non-positive favorite-page numbers after type conversion."""
        if self.page < 1:
            raise HTTP(400, "Ongeldige waarde voor 'page'")

    @property
    def requested_active(self) -> bool:
        """Return the mutation value, requiring it only on mutation routes."""
        if self.active is None:
            raise HTTP(400, "Ontbrekende waarde voor 'active'")
        return self.active


class ProductFavoriteSettings(FavoriteSettings, SettingsFixture[CatalogFavorite]):
    """Favorite request settings for product routes."""

    entity_kind: CatalogEntityKind = "product"

    def on_request(self, context: dict[str, t.Any]) -> None:
        """Parse product favorite settings."""
        super().on_request(context)
        self.validate_page()


class MethodFavoriteSettings(FavoriteSettings, SettingsFixture[CatalogFavorite]):
    """Favorite request settings for method routes."""

    entity_kind: CatalogEntityKind = "method"

    def on_request(self, context: dict[str, t.Any]) -> None:
        """Parse method favorite settings."""
        super().on_request(context)
        self.validate_page()
