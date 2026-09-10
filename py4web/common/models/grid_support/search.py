"""Search form and filter helpers for EddieGrid."""

import ast
import contextlib
import json
import typing as t
import uuid
from copy import deepcopy

import pydal.validators
from py4web.utils.form import Form, FormStyleBootstrap4
from py4web.utils.form import FormStyleFactory as FormStyle
from typedal import QueryBuilder, TypedTable
from typedal.types import Field, Query

from py4web import request
from shared_code.data_model.mixins import SearchMixin
from shared_code.data_model.mixins.search import (
    apply_basic_search,
    basic_search_query,
)

LIMIT_PARAM = "limit"


class LimitConfig(t.TypedDict):
    """Normalized pagination limit configuration."""

    options: dict[int, str] | t.Iterable[int]
    default: int
    param: t.NotRequired[str]


type T_Limit = dict[int, str] | t.Iterable[int] | LimitConfig | t.Literal[False] | None


def get_request_data() -> dict[str, t.Any]:
    """Retrieves and merges data from different parts of an HTTP request.

    This function gathers data from form submissions, query parameters, or JSON-encoded
    bodies in an HTTP request. On key conflicts, form data overrides query params,
    and JSON overrides both.
    """
    json_data = request.json if isinstance(request.json, dict) else {}
    return {**request.query, **request.forms, **json_data}


class SearchField(Field):
    """Extended Field that allows custom query building logic for EddieSearch.

    Supports QueryBuilder operations like joins, aggregates, and having clauses
    for advanced filtering scenarios.

    Falls back to standard .belongs() if no custom query_fn provided.

    Examples:
        # Dict-based lookup (automatically uses values[0] as key)
        SearchField(
            "status_filter",
            query_fn=lambda builder, name, values: {
                "active": builder.where(Table.archived == None),
                "archived": builder.where(Table.archived != None),
                "all": builder,
            },
            requires=IS_IN_SET(["all", "active", "archived"]),
            default="all"
        )

        # Simple conditional with subquery
        SearchField(
            "has_teams",
            query_fn=lambda builder, name, values: (
                builder.where(SchoolProcess.id.belongs(Team.select(Team.school)))
                if values[0] == "yes" else builder
            ),
            requires=IS_IN_SET(["yes", "no"]),
            default="no"
        )

        # Complex OR conditions
        SearchField(
            "search_query",
            query_fn=lambda builder, name, values: (
                builder.where(
                    (Table.name.like(f'%{values[0]}%')) |
                    (Table.code == values[0])
                )
            ),
            label="Search"
        )

        # Subquery with negation
        SearchField(
            "exclude_empty",
            query_fn=lambda builder, name, values: (
                builder.where(
                    ~SchoolProcess.id.belongs(Team.select(Team.school))
                ) if values[0] == "yes" else builder
            ),
            requires=IS_IN_SET(["yes", "no"])
        )

    Important:
        - query_fn can return QueryBuilder OR dict[str, QueryBuilder]
        - If dict is returned, values[0] is used as the lookup key automatically
        - The 'values' parameter is always a list, even for single selections
        - Common patterns:
            * Dict lookup: {key: builder_variant, ...}  # auto-handles .get(values[0])
            * Conditional: builder.where(...) if condition else builder
            * Always chain methods: builder.where(...).join(...)

    """

    def __init__(
        self,
        fieldname: str,
        query_fn: t.Callable[[QueryBuilder, str, list], QueryBuilder | dict[str, QueryBuilder]] | None = None,
        **kwargs: t.Any,
    ) -> None:
        """Initialize a filter field with optional custom query logic.

        Args:
            fieldname: Field name used for the form field.
            query_fn: Custom query builder function.
                Signature: (builder, field_name, filter_values) -> QueryBuilder | dict[str, QueryBuilder]
                - builder: Current QueryBuilder instance
                - field_name: Name of this field (same as `fieldname`).
                - filter_values: List of selected values from the form (always a list).
            **kwargs: Standard Field arguments (requires, default, widget, label, etc.).

        Can return:
            - QueryBuilder: Applied directly.
            - dict[str, QueryBuilder]: Automatically looks up values[0] as key.

        """
        super().__init__(fieldname, **kwargs)
        self.query_fn = query_fn

    @staticmethod
    def apply_standard_filter(table: type[TypedTable], field_name: str, filter_values: list) -> Query:
        """Apply standard .belongs() filter with None handling.

        This is the default behavior for both SearchField (without query_fn)
        and regular Field instances.
        """
        query = table[field_name].belongs(filter_values)
        if "none" in filter_values or None in filter_values:
            query |= table[field_name] == None
        return query

    def apply_filter[T: TypedTable](
        self, table: type[T], builder: QueryBuilder[T], filter_values: list
    ) -> QueryBuilder[T]:
        """Apply this filter to the QueryBuilder.

        Args:
            table: The TypedTable class being queried
            builder: Current QueryBuilder instance
            filter_values: List of filter values from the request

        Returns:
            Updated QueryBuilder with filter applied

        """
        if not self.query_fn:
            return builder.where(self.apply_standard_filter(table, self.name, filter_values))

        result = self.query_fn(builder, self.name, filter_values)

        # Auto-handle dict return: lookup first value as key
        if isinstance(result, dict):
            result = result.get(filter_values[0], builder)

        return t.cast(QueryBuilder[T], result)


class EddieSearch:
    """Build a query and HTMX-backed search form from request filters."""

    builder: QueryBuilder[TypedTable] | None = None

    def __init__(
        self,
        table: type[TypedTable],
        query: Query | bool,
        formstyle: FormStyle = FormStyleBootstrap4,
        search_filters: t.Iterable[Field | SearchField] = (),
        limit: T_Limit = None,
        **kw: t.Any,
    ) -> None:
        """Initialize the search state, filters, and form wiring from a request."""
        super().__init__()

        kw["formstyle"] = formstyle = deepcopy(formstyle)
        formstyle.classes["input[type=submit]"] = "d-none"

        self.data = get_request_data()

        self.form_settings = kw
        self.table = table
        self.query = t.cast(Query, query)
        self.search_filters = list(search_filters)
        self.grid_id = self.data.get("_grid_id") or f"eddie-grid-{uuid.uuid4()}"

        self.search_filters.append(
            Field(
                "q",
                default=self.data.get("q"),
                _placeholder="Begin met zoeken...",
            )
        )

        limit_config = self.limit_config(limit)
        self._limit = limit_config

        if limit_config:
            limit_config.setdefault("param", LIMIT_PARAM)

            self.search_filters.append(
                Field(
                    limit_config["param"],
                    default=self.limit,
                    requires=pydal.validators.IS_IN_SET(limit_config["options"]),
                )
            )

        self.search_form = self.build_search_form()

        if isinstance(table, type) and issubclass(table, TypedTable):
            builder = QueryBuilder(table).where(self.query)

            # process request:
            if search_query := self.data.get("q", "").strip():
                builder = (
                    table.search(search_query, builder=builder)
                    if issubclass(table, SearchMixin)
                    else apply_basic_search(search_query, table, builder)
                )

            # not using self.search_filters here, because that includes stuff like 'q' and 'limit'
            for extra_filter in search_filters:
                filter_name = extra_filter.name

                if filter_value := self.data.get(filter_name, extra_filter.default):
                    if isinstance(filter_value, str):
                        # maybe it's a stringified value (e.g. when paginating)
                        with contextlib.suppress(Exception):
                            filter_value = ast.literal_eval(filter_value)

                    filter_value = [filter_value] if not isinstance(filter_value, list) else filter_value

                    # Use SearchField's custom query logic if available, otherwise standard filter
                    if isinstance(extra_filter, SearchField):
                        builder = extra_filter.apply_filter(table, builder, filter_value)
                    else:
                        # Standard Field: use the same logic as SearchField's default
                        builder = builder.where(SearchField.apply_standard_filter(table, filter_name, filter_value))

            if builder:
                # truthy if any .where or .select was applied
                self.query = builder.query  # convert typedal query builder back into pydal query again

            self.builder = builder
        elif search_query := self.data.get("q", "").strip():
            self.query &= basic_search_query(search_query, table)

    @staticmethod
    def limit_config(limit: T_Limit) -> LimitConfig | None:
        """Normalize the supported limit formats into a typed config mapping."""
        # None = default; False(y) = disable
        if not limit and limit is not None:
            return None

        if limit is None:
            # default
            return LimitConfig(
                options={
                    10: "10 per pagina",
                    50: "50 per pagina",
                    100: "100 per pagina",
                },
                default=10,
                param=LIMIT_PARAM,
            )
        elif isinstance(limit, dict):
            if "options" in limit:
                # already a LimitConfig
                limit_config = t.cast(LimitConfig, limit)

                if "default" not in limit_config:
                    limit_config["default"] = next(iter(limit_config["options"]))

                return limit_config

            # at this point, limit is {i: label}
            limit_simple = t.cast(dict[int, str], limit)

            # -> we can assume at least 1
            return LimitConfig(
                options=limit_simple,
                default=next(iter(limit_simple)),
                param=LIMIT_PARAM,
            )
        else:
            # other iterable
            # we can assume at least 1
            options = [limit_value for limit_value in limit if isinstance(limit_value, int)]
            return LimitConfig(
                options={value: f"{value} per pagina" for value in options},
                default=options[0],
                param=LIMIT_PARAM,
            )

    @property
    def orderby(self) -> str | None:
        """Return the current order-by expression, if any."""
        if not self.builder:
            return None

        orderby = self.builder.select_kwargs.get("orderby")
        return str(orderby) if orderby else None

    @property
    def limit(self) -> int:
        """Return the active page size."""
        if not self._limit:
            return 0

        param = self._limit["param"]
        default = self._limit["default"]
        return int(self.data.get(param) or default)

    def build_search_form(self) -> Form:
        """Build the HTMX search form used to filter the grid."""
        search_filter_names = {field.name for field in self.search_filters}
        persistent_query_params: dict[str, t.Any] = {}
        for key in request.query:
            if key.startswith("_") or key in search_filter_names:
                continue

            value = request.query.get(key)
            if value not in (None, ""):
                persistent_query_params[key] = value

        hx_form_attrs = {
            "_hx-post": request.url.split("?")[0],
            "_hx-trigger": "ew:search throttle:500ms",
            "_hx-target": f".{self.grid_id} .grid-table-wrapper",
            "_hx-select": f".{self.grid_id} .grid-table-wrapper",
            # ^ this replaces the main table. hx-swap-oob is used to swap out the footer.
            "_hx-vals": json.dumps({"_grid_id": self.grid_id, **persistent_query_params}),
            "_hx-swap": "outerHTML",
            "_hx-encoding": "application/x-www-form-urlencoded",
            "_method": "POST",
            "__": """
            on submit
                halt -- prevent actual submit
            end -- on submit
            on htmx:beforeRequest
                -- store state in url
                call update_url_params(event.detail.requestConfig.parameters)
            end
            on change
                -- note: skip 'q' because otherwise it would trigger twice
                if the event's target's name != 'q'
                    send ew:search

            end -- change
            on keyup debounced at 300ms -- not also on submit
                send ew:search -- with extra throttle
            end -- keyup
            """,
        }
        return Form(
            self.search_filters,
            # keep_values=True,
            form_name="eddie_search",
            **hx_form_attrs,
            **self.form_settings,
        )
