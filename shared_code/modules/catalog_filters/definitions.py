"""Filter definition implementations for catalogue filters."""

import math
import typing as t

from typedal import QueryBuilder
from typedal.fields import Field
from yatl import TAGGER as HTMLElement
from yatl.helpers import BUTTON, DIV, INPUT, LABEL, OPTION, SELECT, SPAN

from shared_code.data_model import Method, Supplier
from shared_code.data_model.mixins.search import SearchMixin
from shared_code.data_model.tables.product import PRODUCT_COMPOSITION_LABELS
from shared_code.util.html import convert_attrs

from .types import CatalogFilterContext, DynamicFilterMetadata, FilterOption

VISIBLE_PRODUCT_COMPOSITIONS = ("single", "package")
BUDGET_BRACKETS = (
    (0.0, 0.01, "Onbekend"),
    (0.01, 10.0, "€ 0 - € 10"),
    (10.0, 15.0, "€ 10 - € 15"),
    (15.0, 20.0, "€ 15 - € 20"),
    (20.0, 30.0, "€ 20 - € 30"),
    (30.0, 50.0, "€ 30 - € 50"),
    (50.0, 9999.0, "€ 50 +"),
)


class InvalidCatalogFilterValue(ValueError):
    """Raised when a request value cannot be used by a catalogue filter."""

    def __init__(self, slug: str) -> None:
        """Initialize the error for the filter identified by `slug`."""
        super().__init__(f"Invalid value for catalogue filter {slug!r}")


def flatten_filter_values(values: list[t.Any]) -> t.Iterable[t.Any]:
    """Flatten list-field distinct values into scalar option values."""
    for value in values:
        if value is None:
            continue
        if isinstance(value, list):
            yield from value
            continue
        yield value


def stringify_filter_value(value: t.Any) -> str:
    """Convert one filter value into its querystring representation."""
    if value is None:
        return ""
    return str(value).strip()


def as_flat_value_list(value: t.Any | None) -> list[str]:
    """Normalize a flat scalar/list filter value into a list of strings."""
    if value is None:
        return []
    elif isinstance(value, str):
        return [value]
    elif isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    else:
        return []


def normalized_distinct_values(values: list[str]) -> list[str]:
    """Normalize, deduplicate, and preserve request values in order."""
    normalized: list[str] = []
    seen: set[str] = set()

    for value in values:
        stripped_value = value.strip()
        if not stripped_value or stripped_value in seen:
            continue
        seen.add(stripped_value)
        normalized.append(stripped_value)

    return normalized


def represent_filter_value(field: Field, value: t.Any) -> str:
    """Render one option label using the field representer when available."""
    if str(field.type).startswith("list:"):
        return stringify_filter_value(value)

    represent = getattr(field, "represent", None)
    if callable(represent):
        try:
            rendered = represent(value, None)
        except TypeError:
            rendered = represent(value)
        if rendered is not None:
            return str(rendered)
    return stringify_filter_value(value)


class BaseCatalogFilterDefinition:
    """Shared filter contract used by search, dynamic, and custom filters."""

    def __init__(self, metadata: DynamicFilterMetadata, context: CatalogFilterContext) -> None:
        """Store the metadata and request context shared by all filter types."""
        self.metadata = metadata
        self.context = context
        self.current_value: str | list[str] | bool | None = None
        self._options: list[FilterOption] | None = None

    @property
    def slug(self) -> str:
        """Return the querystring key for this filter."""
        return self.metadata.slug

    @property
    def label(self) -> str:
        """Return the display label for this filter."""
        return self.metadata.label

    def parse(self) -> str | list[str] | bool | None:
        """Parse the active request value for this filter."""
        raise NotImplementedError

    def apply(self, builder: QueryBuilder[t.Any], active_value: str | list[str] | bool) -> QueryBuilder[t.Any]:
        """Apply the active value to an existing query builder."""
        raise NotImplementedError

    @property
    def placeholder(self) -> str:
        """Return placeholder text for rendered inputs, if any."""
        return ""

    @property
    def widget_kind(self) -> str:
        """Return the widget family used to render this filter."""
        return self.metadata.widget_kind or "select"

    def build_options(self) -> list[FilterOption]:
        """Query this filter's selectable options. Filters that have none keep this."""
        return []

    def options(self) -> list[FilterOption]:
        """Return this filter's options, building them at most once.

        Memoized so that forcing them up front and rendering afterwards costs one
        set of queries, not two. Rendering asks for them through here, so a caller
        that never forces them still works; it just pays during rendering.
        """
        if self._options is None:
            self._options = self.build_options()
        return self._options

    def set_options(self, options: t.Iterable[FilterOption]) -> None:
        """Seed the options from outside, instead of querying for them.

        Lets a cached payload stand in for `build_options()`, so a hit renders
        without touching the database.
        """
        self._options = list(options)

    @property
    def field(self) -> Field:
        """Return the bound database field for this filter."""
        if not self.metadata.field_name:
            raise KeyError(f"Filter {self.slug} has no field_name")
        return self.context.table[self.metadata.field_name]

    def filter_id(self) -> str:
        """Return the DOM id used for the filter control."""
        return f"filter-{self.slug}"

    def render(self) -> HTMLElement:
        """Render the default select-based filter control."""
        if self.widget_kind == "multi-select":
            return self.render_capsule_dropdown(multiple=True)
        elif self.widget_kind == "select":
            current_values = self.current_value if isinstance(self.current_value, list) else []
            return self.render_capsule_dropdown(multiple=len(current_values) > 1)

        options = self.options()
        return DIV(
            LABEL(self.label, _class="form-label", _for=self.filter_id()),
            SELECT(
                OPTION("Alles", _value=""),
                *[
                    OPTION(
                        option.label,
                        _value=option.value,
                        _selected=self.current_value == option.value,
                    )
                    for option in options
                ],
                _id=self.filter_id(),
                _name=self.slug,
                _class="form-select",
            ),
        )

    def render_capsule_dropdown(self, multiple: bool, option_limit: int = 100) -> HTMLElement:
        """Render the capsule dropdown widget for single- and multi-select filters."""
        options = self.options()
        current_values = self.current_value if isinstance(self.current_value, list) else []
        current_value = self.current_value if isinstance(self.current_value, str) else ""
        if multiple:
            selected_values = set(current_values)
        else:
            selected_values = set(current_values[:1] or ([current_value] if current_value else []))
        windowed = len(options) > option_limit
        visible_options = options[:option_limit] if windowed else options
        if windowed:
            visible_values = {option.value for option in visible_options}
            visible_options = [
                *[
                    option
                    for option in options
                    if option.value in selected_values and option.value not in visible_values
                ],
                *visible_options,
            ]
        input_type = "checkbox" if multiple else "radio"
        widget_kind = "multi-select" if multiple else "single-select"

        return DIV(
            LABEL(self.label, _class="form-label", _for=self.filter_id()),
            DIV(
                BUTTON(
                    SPAN("Alles", _class="selected-text is-placeholder"),
                    SPAN("", _class="dropdown-icon"),
                    **convert_attrs(
                        {
                            "class": "btn btn-light dropdown-toggle",
                            "type": "button",
                            "id": self.filter_id(),
                            "data-bs-toggle": "dropdown",
                            "data-bs-auto-close": "outside",
                            "aria-expanded": "false",
                            "aria-label": self.label,
                        },
                    ),
                ),
                DIV(
                    DIV(
                        INPUT(
                            **convert_attrs(
                                {
                                    "type": "search",
                                    "class": "capsule-search-input",
                                    "placeholder": "Zoek...",
                                    "aria-label": "Zoek opties",
                                },
                            ),
                        ),
                        _class="capsule-search-container",
                    ),
                    DIV(
                        *[
                            LABEL(
                                INPUT(
                                    _class="form-check-input",
                                    _type=input_type,
                                    _name=self.slug,
                                    _value=option.value,
                                    _checked=option.value in selected_values,
                                ),
                                SPAN(option.label, _class="item-label"),
                                **convert_attrs(
                                    {
                                        "class": "dropdown-item d-flex align-items-center"
                                        + (" selected" if option.value in selected_values else ""),
                                        "role": "option",
                                        "aria-selected": "true" if option.value in selected_values else "false",
                                        "data-search": f"{(option.label or '').lower()} {(option.value or '').lower()}",
                                    },
                                ),
                            )
                            for option in visible_options
                        ],
                        _class="search-results",
                    ),
                    DIV(
                        SPAN("0 geselecteerd", _class="selected-count small"),
                        BUTTON("Klaar", _type="button", _class="close-dropdown-btn"),
                        _class="capsule-dropdown-footer",
                    ),
                    **convert_attrs(
                        {
                            "class": "dropdown-menu capsule-dropdown-menu",
                            "role": "listbox",
                            "aria-multiselectable": "true" if multiple else "false",
                        },
                    ),
                ),
                **convert_attrs(
                    {
                        "class": "capsule-dropdown",
                        "data-widget": widget_kind,
                        "data-placeholder": "Alles",
                        "data-option-slug": self.slug if windowed else None,
                        "data-option-kind": self.context.entity_kind if windowed else None,
                        "data-option-limit": str(option_limit) if windowed else None,
                    },
                ),
            ),
        )


class SearchFilterDefinition(BaseCatalogFilterDefinition):
    """Free-text filter using the SearchMixin search implementation."""

    @property
    def widget_kind(self) -> str:
        """Search filters render as a text search input."""
        return "search"

    @property
    def placeholder(self) -> str:
        """Return entity-specific placeholder text for the search input."""
        if self.context.entity_kind == "product":
            return "Zoek op naam, OLID of ISBN"
        return "Zoek op naam of OLID"

    def parse(self) -> str | list[str] | bool | None:
        """Parse the first non-empty search term from the request."""
        values = as_flat_value_list(self.context.params.get(self.slug))
        search = values[0].strip() if values else ""
        return search or None

    def apply(self, builder: QueryBuilder[t.Any], active_value: str | list[str] | bool) -> QueryBuilder[t.Any]:
        """Delegate filtering to the table's search implementation."""
        table = self.context.table
        if isinstance(table, type) and issubclass(table, SearchMixin):
            return table.apply_search(t.cast(str, active_value), builder)
        return builder

    def render(self) -> HTMLElement:
        """Render the search input control."""
        return DIV(
            LABEL(self.label, _class="form-label", _for=self.filter_id()),
            INPUT(
                _id=self.filter_id(),
                _name=self.slug,
                _class="form-control",
                _type="search",
                _value=self.current_value or "",
                _placeholder=self.placeholder,
            ),
        )


class DynamicFieldFilterDefinition(BaseCatalogFilterDefinition):
    """Generic field-based filter backed by DynamicFilter metadata."""

    def parse(self) -> str | list[str] | bool | None:
        """Parse the request value for the bound field."""
        values = as_flat_value_list(self.context.params.get(self.slug))
        field_type = str(self.field.type)

        if not field_type.startswith("list:") and self.widget_kind != "multi-select":
            value = values[0].strip() if values else ""
            return value or None

        normalized = normalized_distinct_values(values)
        return normalized or None

    def apply(self, builder: QueryBuilder[t.Any], active_value: str | list[str] | bool) -> QueryBuilder[t.Any]:
        """Apply the parsed field value to the query builder."""
        field = self.field
        raw_values = [active_value] if isinstance(active_value, str) else t.cast(list[str], active_value)
        values = [value for value in raw_values if value]
        if not values:
            return builder

        def build_or_contains() -> t.Any:
            query = None
            for value in values:
                clause = field.contains(value)
                query = clause if query is None else query | clause
            return query

        field_type = str(field.type)

        if field_type.startswith("list:") or self.metadata.match_mode == "contains":
            return builder.where(build_or_contains())
        else:
            return builder.where(field.belongs(values))

    @property
    def widget_kind(self) -> str:
        """Render list fields as a multi-select widget."""
        if str(self.field.type).startswith("list:"):
            return "multi-select"
        if self.metadata.widget_kind == "select":
            return "multi-select"
        return self.metadata.widget_kind or "select"

    def build_options(self) -> list[FilterOption]:
        """Return distinct options derived from the bound field."""
        field = self.field
        values = self.context.option_builder.column(field, distinct=field)
        options: list[FilterOption] = []
        seen: set[str] = set()

        for value in flatten_filter_values(values):
            string_value = stringify_filter_value(value)
            if not string_value or string_value in seen:
                continue
            seen.add(string_value)
            options.append(FilterOption(value=string_value, label=represent_filter_value(field, value)))

        return sorted(options, key=lambda option: option.label.casefold())


class HasValueFilterDefinition(BaseCatalogFilterDefinition):
    """Custom filter that matches rows with a non-empty value in one field."""

    @property
    def widget_kind(self) -> str:
        """Render this filter as a checkbox."""
        return "checkbox"

    def parse(self) -> str | list[str] | bool | None:
        """Return whether the checkbox was enabled in the request."""
        return bool(as_flat_value_list(self.context.params.get(self.slug)))

    def apply(self, builder: QueryBuilder[t.Any], active_value: str | list[str] | bool) -> QueryBuilder[t.Any]:
        """Filter out rows where the bound field is empty."""
        if not active_value:
            return builder

        field = self.field
        return builder.where((field != None) & (field != ""))

    def render(self) -> HTMLElement:
        """Render the checkbox control."""
        return DIV(
            INPUT(
                _class="form-check-input",
                _type="checkbox",
                _id=self.filter_id(),
                _name=self.slug,
                _value="1",
                _checked=bool(self.current_value),
            ),
            LABEL(self.label, _class="form-check-label", _for=self.filter_id()),
            _class="form-check",
        )


class BooleanChoiceFilterDefinition(BaseCatalogFilterDefinition):
    """Select filter that renders booleans as Dutch yes/no labels."""

    def parse(self) -> str | list[str] | bool | None:
        """Parse one scalar filter value."""
        values = as_flat_value_list(self.context.params.get(self.slug))
        value = values[0].strip() if values else ""
        return value or None

    def apply(self, builder: QueryBuilder[t.Any], active_value: str | list[str] | bool) -> QueryBuilder[t.Any]:
        """Apply the selected boolean value."""
        if active_value not in ("T", "F"):
            raise InvalidCatalogFilterValue(self.slug)

        return builder.where(self.field == (active_value == "T"))

    def build_options(self) -> list[FilterOption]:
        """Only show boolean options that are actually present in the current scope."""
        values = self.context.option_builder.column(self.field, distinct=self.field)
        options: list[FilterOption] = []
        seen: set[str] = set()

        for value in values:
            if value is None:
                continue

            option_value = "T" if bool(value) else "F"
            if option_value in seen:
                continue

            seen.add(option_value)
            options.append(FilterOption(value=option_value, label="Ja" if option_value == "T" else "Nee"))

        return options


class BudgetFilterDefinition(BaseCatalogFilterDefinition):
    """Select filter for the old public guide-price brackets."""

    @property
    def widget_kind(self) -> str:
        """Guide-price brackets support OR selection across multiple ranges."""
        return "multi-select"

    def parse(self) -> str | list[str] | bool | None:
        """Parse selected budget range values."""
        values = as_flat_value_list(self.context.params.get(self.slug))
        normalized = normalized_distinct_values(values)
        return normalized or None

    def apply(self, builder: QueryBuilder[t.Any], active_value: str | list[str] | bool) -> QueryBuilder[t.Any]:
        """Apply the selected price brackets with OR semantics."""
        raw_values = [active_value] if isinstance(active_value, str) else t.cast(list[str], active_value)
        values = [value for value in raw_values if value]
        if not values:
            return builder

        query = None
        field = self.field

        for value in values:
            lower_raw, _, upper_raw = value.partition("-")
            if not lower_raw or not upper_raw:
                raise InvalidCatalogFilterValue(self.slug)

            try:
                lower = float(lower_raw)
                upper = float(upper_raw)
            except ValueError as exc:
                raise InvalidCatalogFilterValue(self.slug) from exc
            if not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper:
                raise InvalidCatalogFilterValue(self.slug)

            clause = (field >= lower) & (field < upper)
            query = clause if query is None else query | clause

        if query is None:
            return builder

        return builder.where(query)

    def build_options(self) -> list[FilterOption]:
        """Return the fixed public price brackets from the old platform."""
        return [FilterOption(value=f"{lower}-{upper}", label=label) for lower, upper, label in BUDGET_BRACKETS]


class SupplierFilterDefinition(BaseCatalogFilterDefinition):
    """Lookup filter that renders supplier gids as supplier names."""

    @property
    def widget_kind(self) -> str:
        """Suppliers support OR selection across multiple gids."""
        return "multi-select"

    def parse(self) -> str | list[str] | bool | None:
        """Parse selected supplier gids."""
        values = as_flat_value_list(self.context.params.get(self.slug))
        normalized = normalized_distinct_values(values)
        return normalized or None

    def apply(self, builder: QueryBuilder[t.Any], active_value: str | list[str] | bool) -> QueryBuilder[t.Any]:
        """Filter on one or more supplier gids."""
        raw_values = [active_value] if isinstance(active_value, str) else t.cast(list[str], active_value)
        values = [value for value in raw_values if value]
        if not values:
            return builder

        return builder.where(self.field.belongs(values))

    def build_options(self) -> list[FilterOption]:
        """Resolve supplier gids in scope to readable supplier names."""
        gids = [
            stringify_filter_value(value)
            for value in self.context.option_builder.column(self.field, distinct=self.field)
            if stringify_filter_value(value)
        ]
        if not gids:
            return []

        rows = Supplier.where(Supplier.gid.belongs(gids)).select(orderby=Supplier.name).collect()
        return [FilterOption(value=row.gid, label=row.name) for row in rows if row.name]


class MethodLookupFilterDefinition(BaseCatalogFilterDefinition):
    """Lookup filter that renders product method gids as method names."""

    @property
    def widget_kind(self) -> str:
        """Methods support OR selection across multiple gids."""
        return "multi-select"

    def parse(self) -> str | list[str] | bool | None:
        """Parse selected method gids."""
        values = as_flat_value_list(self.context.params.get(self.slug))
        normalized = normalized_distinct_values(values)
        return normalized or None

    def apply(self, builder: QueryBuilder[t.Any], active_value: str | list[str] | bool) -> QueryBuilder[t.Any]:
        """Filter products on one or more method gids."""
        raw_values = [active_value] if isinstance(active_value, str) else t.cast(list[str], active_value)
        values = [value for value in raw_values if value]
        if not values:
            return builder

        return builder.where(self.field.belongs(values))

    def build_options(self) -> list[FilterOption]:
        """Resolve method gids in scope to readable method names."""
        gids = [
            stringify_filter_value(value)
            for value in self.context.option_builder.column(self.field, distinct=self.field)
            if stringify_filter_value(value)
        ]
        if not gids:
            return []

        rows = Method.where(Method.gid.belongs(gids)).select(orderby=Method.name).collect()
        return [FilterOption(value=row.gid, label=row.name) for row in rows if row.name]


class ProductCompositionFilterDefinition(BaseCatalogFilterDefinition):
    """Select filter that mirrors the old visible product composition subset."""

    @property
    def widget_kind(self) -> str:
        """Composition supports OR selection across multiple values."""
        return "multi-select"

    def parse(self) -> str | list[str] | bool | None:
        """Parse selected composition values."""
        values = as_flat_value_list(self.context.params.get(self.slug))
        normalized = normalized_distinct_values(values)
        return normalized or None

    def apply(self, builder: QueryBuilder[t.Any], active_value: str | list[str] | bool) -> QueryBuilder[t.Any]:
        """Filter products on one or more visible compositions."""
        raw_values = [active_value] if isinstance(active_value, str) else t.cast(list[str], active_value)
        values = [value for value in raw_values if value]
        if not values:
            return builder

        return builder.where(self.field.belongs(values))

    def build_options(self) -> list[FilterOption]:
        """Expose only the public composition values from the old platform."""
        values = {
            stringify_filter_value(value)
            for value in self.context.option_builder.column(self.field, distinct=self.field)
            if stringify_filter_value(value)
        }
        return [
            FilterOption(value=composition, label=PRODUCT_COMPOSITION_LABELS[composition])
            for composition in VISIBLE_PRODUCT_COMPOSITIONS
            if composition in values and composition in PRODUCT_COMPOSITION_LABELS
        ]


CUSTOM_FILTERS: dict[str, type[BaseCatalogFilterDefinition]] = {
    "boolean_choice": BooleanChoiceFilterDefinition,
    "budget_range": BudgetFilterDefinition,
    "has_value": HasValueFilterDefinition,
    "method_lookup": MethodLookupFilterDefinition,
    "product_composition": ProductCompositionFilterDefinition,
    "supplier_lookup": SupplierFilterDefinition,
}
