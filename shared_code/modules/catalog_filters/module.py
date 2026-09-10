"""Catalogue filter loading, parsing, rendering, and query application."""

import typing as t

from endow import Domain
from typedal import QueryBuilder

from shared_code.data_model import AnyDict, DynamicFilter, DynamicSort, Method, Product
from shared_code.data_model.constants import CATALOG_APPLIES_TO_LABELS
from shared_code.data_model.validators.sort_expression import parse_sort_expression

from .definitions import (
    CUSTOM_FILTERS,
    BaseCatalogFilterDefinition,
    DynamicFieldFilterDefinition,
    SearchFilterDefinition,
)
from .types import (
    CatalogEntityKind,
    CatalogFilterContext,
    CatalogSortOption,
    DynamicFilterMetadata,
    ResolvedCatalogFilters,
)


class CatalogFilters(Domain):
    """Resolve, render, and apply catalogue filters for products and methods."""

    def resolve(
        self,
        entity_kind: CatalogEntityKind,
        *,
        params: AnyDict,
        option_builder: QueryBuilder[t.Any],
        sort_options: dict[str, CatalogSortOption[t.Any]] | None = None,
    ) -> ResolvedCatalogFilters:
        """Resolve active filter definitions for one request."""
        if entity_kind not in t.get_args(CatalogEntityKind):
            raise ValueError("invalid 'entity_kind'")

        context = CatalogFilterContext(
            entity_kind=entity_kind,
            table=self._table_for(entity_kind),
            params=params,
            option_builder=option_builder,
        )

        definitions = self._definitions_for_context(context)
        active_definitions: list[tuple[BaseCatalogFilterDefinition, str | list[str] | bool]] = []
        active_filter_count = 0

        for definition in definitions:
            active_value = definition.parse()
            definition.current_value = active_value
            if active_value in (None, False):
                continue
            active_filter_count += 1
            active_definitions.append((definition, active_value))

        return ResolvedCatalogFilters(
            entity_kind=entity_kind,
            filters=definitions,
            active_definitions=active_definitions,
            active_filter_count=active_filter_count,
            sort_options=sort_options or {},
        )

    def apply(
        self,
        builder: QueryBuilder[t.Any],
        resolved_filters: ResolvedCatalogFilters | None = None,
    ) -> QueryBuilder[t.Any]:
        """Apply resolved filters to an existing base builder."""
        if resolved_filters is None:
            return builder

        for definition, active_value in resolved_filters.active_definitions:
            builder = definition.apply(builder, active_value)

        return builder

    def _definitions_for_context(self, context: CatalogFilterContext) -> list[BaseCatalogFilterDefinition]:
        definitions: list[BaseCatalogFilterDefinition] = []

        rows = (
            DynamicFilter.where(DynamicFilter.is_active == True)
            .select(orderby=(DynamicFilter.sort_order, DynamicFilter.id))
            .collect()
        )
        for row in rows:
            metadata = DynamicFilterMetadata(
                slug=row.slug,
                label=row.label,
                filter_kind=row.filter_kind,
                field_name=row.field_name,
                match_mode=row.match_mode,
                applies_to=row.applies_to,
                handler_key=row.handler_key,
                widget_kind=row.widget_kind,
                sort_order=row.sort_order,
            )
            if metadata.applies_to not in CATALOG_APPLIES_TO_LABELS:
                print(
                    "[filters] skipping filter with invalid applies_to:",
                    metadata.slug,
                    metadata.applies_to,
                )
                continue
            if metadata.applies_to not in (context.entity_kind, "both"):
                continue

            definition = self._build_definition(metadata, context)
            if definition is not None:
                definitions.append(definition)

        return definitions

    def _build_definition(
        self, metadata: DynamicFilterMetadata, context: CatalogFilterContext
    ) -> BaseCatalogFilterDefinition | None:
        if metadata.filter_kind == "search":
            return SearchFilterDefinition(metadata, context)

        elif metadata.filter_kind == "dynamic":
            if not metadata.field_name or metadata.field_name not in context.table.fields:
                print(
                    "[filters] skipping dynamic filter with invalid field_name:",
                    metadata.slug,
                    metadata.field_name,
                    context.entity_kind,
                )
                return None
            return DynamicFieldFilterDefinition(metadata, context)

        elif metadata.filter_kind == "custom":
            if not metadata.field_name or metadata.field_name not in context.table.fields:
                print(
                    "[filters] skipping custom filter with invalid field_name:",
                    metadata.slug,
                    metadata.field_name,
                    context.entity_kind,
                )
                return None
            if not metadata.handler_key:
                print("[filters] skipping custom filter without handler_key:", metadata.slug)
                return None
            handler = CUSTOM_FILTERS.get(metadata.handler_key)
            if not handler:
                print(
                    "[filters] skipping custom filter with unknown handler_key:",
                    metadata.slug,
                    metadata.handler_key,
                )
                return None
            return handler(metadata, context)

        print("[filters] skipping filter with unknown filter_kind:", metadata.slug, metadata.filter_kind)
        return None

    def sort_options(self, entity_kind: CatalogEntityKind) -> dict[str, CatalogSortOption[t.Any]]:
        """Load active public sort options for one catalogue entity kind."""
        if entity_kind not in t.get_args(CatalogEntityKind):
            raise ValueError("invalid 'entity_kind'")

        table = self._table_for(entity_kind)
        options: dict[str, CatalogSortOption[t.Any]] = {}
        rows = (
            DynamicSort.where((DynamicSort.is_active == True) & (DynamicSort.applies_to.belongs((entity_kind, "both"))))
            .select(orderby=(DynamicSort.sort_order, DynamicSort.id))
            .collect()
        )

        for row in rows:
            order = self._parse_sort_expression(table, row.order_expression or "")
            if order is None:
                continue

            options[str(row.slug)] = CatalogSortOption(
                label=str(row.label),
                order=order,
                is_default=bool(row.is_default),
            )

        return options

    def default_sort_option(self, entity_kind: CatalogEntityKind) -> CatalogSortOption[t.Any]:
        """Return the configured default sort option, or a stable built-in fallback."""
        options = self.sort_options(entity_kind)
        for option in options.values():
            if option.is_default:
                return option

        return next(iter(options.values())) if options else self.fallback_sort_option(entity_kind)

    @classmethod
    def fallback_sort_option(cls, entity_kind: CatalogEntityKind) -> CatalogSortOption[t.Any]:
        """Return the built-in stable sort option for one catalogue entity kind."""
        return CatalogSortOption(label="ID", order=cls._table_for(entity_kind).id, is_default=True)

    def sort_option(self, entity_kind: CatalogEntityKind, sort: str) -> CatalogSortOption[t.Any]:
        """Return the requested sort option, falling back to the configured default."""
        return self.sort_options(entity_kind).get(sort) or self.default_sort_option(entity_kind)

    @staticmethod
    def _table_for(entity_kind: CatalogEntityKind) -> type[Product] | type[Method]:
        """Return the database table associated with one catalogue entity kind."""
        if entity_kind == "product":
            return Product
        elif entity_kind == "method":
            return Method
        else:
            raise ValueError("invalid 'entity_kind'")

    @staticmethod
    def _parse_sort_expression(
        table: type[Product] | type[Method],
        order_expression: str,
    ) -> t.Any:
        """Parse a persisted order expression into a typed orderby value."""
        return parse_sort_expression(table, order_expression)[0]
