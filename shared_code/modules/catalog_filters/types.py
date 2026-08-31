"""Shared types for catalogue filter orchestration."""

import dataclasses as dc
import typing as t

from typedal import QueryBuilder, TypedTable
from typedal.types import OrderBy

from shared_code.data_model import AnyDict, Method, Product

if t.TYPE_CHECKING:
    from shared_code.modules.catalog_filters.definitions import BaseCatalogFilterDefinition

CatalogEntityKind = t.Literal["product", "method"]


@dc.dataclass(frozen=True)
class FilterOption:
    """One selectable value for a rendered filter control."""

    value: str
    label: str


@dc.dataclass(frozen=True)
class CatalogSortOption[T: TypedTable]:
    """One selectable catalogue sort option."""

    label: str
    order: OrderBy | t.Literal["random"]
    is_default: bool = False


@dc.dataclass(frozen=True)
class CatalogFilterContext:
    """Context shared by filter definitions while building a listing."""

    entity_kind: CatalogEntityKind
    table: type[Product] | type[Method]
    params: AnyDict
    option_builder: QueryBuilder[t.Any]


@dc.dataclass(frozen=True)
class DynamicFilterMetadata:
    """Subset of persisted filter config needed by the runtime module."""

    slug: str
    label: str
    filter_kind: str
    field_name: str | None
    match_mode: str
    applies_to: str
    handler_key: str | None
    widget_kind: str | None
    sort_order: int


@dc.dataclass(frozen=True)
class ResolvedCatalogFilters:
    """Resolved filter definitions plus active values for one request."""

    entity_kind: CatalogEntityKind
    filters: list[BaseCatalogFilterDefinition]
    active_definitions: list[tuple[BaseCatalogFilterDefinition, str | list[str] | bool]]
    active_filter_count: int
    sort_options: dict[str, CatalogSortOption[t.Any]] = dc.field(default_factory=dict)
