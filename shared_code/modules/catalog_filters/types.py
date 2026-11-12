"""Shared types for catalogue filter orchestration."""

import dataclasses as dc
import json
import typing as t

from typedal import QueryBuilder, TypedTable
from typedal.types import OrderBy

from shared_code.data_model import AnyDict, Method, Product, ProductEd
from shared_code.data_model.constants.catalog import CatalogListingKind
from shared_code.data_model.validators.sort_expression import (
    CatalogSortTable,
    restore_sort_expression,
    sort_expression_table_name,
    stringify_sort_expression,
)
from shared_code.util.types import CachableProtocol

if t.TYPE_CHECKING:
    from shared_code.modules.catalog_filters.definitions import BaseCatalogFilterDefinition


@dc.dataclass(frozen=True)
class FilterOption:
    """One selectable value for a rendered filter control."""

    value: str
    label: str


def find_filter_table(name: str) -> CatalogSortTable:
    """Resolve a cached catalogue table name to its currently bound model."""
    # from_dillable has no database instance for db.find_model, so resolve
    # the stored table name through the known catalogue models instead.
    tables = {"product": Product, "method": Method}

    table = tables.get(name)
    if table is None:
        raise ValueError(f"Unknown cached catalogue sort table: {name}")

    return table


@dc.dataclass(frozen=True)
class CatalogSortOption[T: TypedTable](CachableProtocol):
    """One selectable catalogue sort option."""

    label: str
    order: OrderBy | t.Literal["random"]
    is_default: bool = False
    dynamic_sort_ed_id: int | None = None
    _model: str = dc.field(default="", repr=False, compare=False)

    def to_dillable(self) -> t.Self:
        """Replace bound fields with the catalogue's plain sort expression."""
        return dc.replace(
            self,
            order=stringify_sort_expression(self.order),
            _model=sort_expression_table_name(self.order) or "",
        )

    @classmethod
    def from_dillable(cls, value: t.Self) -> t.Self:
        """Rebind a cached sort expression to the current catalogue table."""
        tablename = value._model
        if not tablename:
            return value

        order = restore_sort_expression(find_filter_table(tablename), t.cast(str, value.order))
        return dc.replace(value, order=order, _model="")


@dc.dataclass(frozen=True)
class CatalogFilterContext:
    """Context shared by filter definitions while building a listing."""

    entity_kind: CatalogListingKind
    table: CatalogSortTable | type[ProductEd]
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
    dynamic_filter_ed_id: int | None = None


@dc.dataclass(frozen=True)
class CatalogOptionPage:
    """One search window plus selected options that must remain visible."""

    definition: BaseCatalogFilterDefinition
    options: list[FilterOption]
    selected_options: list[FilterOption]
    next_offset: int
    has_more: bool


@dc.dataclass(frozen=True)
class ResolvedCatalogFilters:
    """Resolved filter definitions plus active values for one request."""

    entity_kind: CatalogListingKind
    filters: list[BaseCatalogFilterDefinition]
    active_definitions: list[tuple[BaseCatalogFilterDefinition, str | list[str] | bool]]
    active_filter_count: int
    sort_options: dict[str, CatalogSortOption[t.Any]] = dc.field(default_factory=dict)

    def __str__(self) -> str:
        """Return stable cache input without query builders or loaded option lists."""
        return json.dumps(
            {
                "entity_kind": self.entity_kind,
                "active_filters": [
                    {"metadata": dc.asdict(definition.metadata), "value": value}
                    for definition, value in self.active_definitions
                ],
                "sort_options": {
                    slug: {"order": str(option.order), "dynamic_sort_ed_id": option.dynamic_sort_ed_id}
                    for slug, option in self.sort_options.items()
                },
            },
            sort_keys=True,
        )

    def __repr__(self) -> str:
        """Wrap the stable string representation with the class name."""
        return f"{type(self).__name__}({self!s})"

    def option_page(self, slug: str, query: str, offset: int, limit: int) -> CatalogOptionPage:
        """Search one filter's cached options and retain its active selections."""
        # TODO: Page the source query if loading or searching the full cached list becomes costly.
        definition = next((item for item in self.filters if item.slug == slug), None)
        if definition is None:
            raise KeyError(slug)

        all_options = definition.options()
        needle = query.strip().casefold()
        matches = [option for option in all_options if definition.matches_option(option, needle)]
        options = matches[offset : offset + limit]
        next_offset = offset + len(options)
        current_value = definition.current_value
        if isinstance(current_value, list):
            selected_values = set(current_value)
        elif isinstance(current_value, str):
            selected_values = {current_value}
        else:
            selected_values = set()

        selected_options = []
        if offset == 0:
            selected_options = [option for option in all_options if option.value in selected_values]
        options = [option for option in options if option.value not in selected_values]

        return CatalogOptionPage(
            definition=definition,
            options=options,
            selected_options=selected_options,
            next_offset=next_offset,
            has_more=next_offset < len(matches),
        )

    def load_options(self) -> t.Self:
        """Run every filter's option queries now, so rendering only formats them.

        Resolving is lazy by default, which puts one distinct-value query per
        filter inside the template. That is the bulk of what the filters endpoint
        costs, and it belongs in the handler where it can be seen, measured and
        cached. Returns self so a handler can resolve and load in one expression.
        """
        for definition in self.filters:
            definition.options()
        return self

    def options_payload(self) -> dict[str, list[tuple[str, str]]]:
        """Project the loaded options into plain data a cache can hold.

        Tuples of strings rather than the objects themselves: the definitions
        carry a `QueryBuilder`, and through it a live database handle, and plain
        data also survives a deploy that changed these classes.
        """
        return {
            definition.slug: [(option.value, option.label) for option in definition.options()]
            for definition in self.filters
        }

    def apply_options(self, payload: t.Mapping[str, t.Sequence[t.Sequence[str]]]) -> t.Self:
        """Seed the filters from a cached payload instead of querying.

        A slug the payload does not mention is left alone, so a filter added
        since the entry was written still loads its own options rather than
        coming back empty.
        """
        for definition in self.filters:
            cached = payload.get(definition.slug)
            if cached is not None:
                definition.set_options(FilterOption(value=value, label=label) for value, label in cached)
        return self
