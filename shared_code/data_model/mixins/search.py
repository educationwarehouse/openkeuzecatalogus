"""Search helpers and mixin utilities for typedal models."""

import enum
import shlex
import typing as t
from dataclasses import dataclass

from pydal.helpers.classes import SQLCustomType
from typedal import QueryBuilder
from typedal.fields import Field, rname
from typedal.mixins import Mixin
from typedal.tables import _TypedTable
from typedal.types import OrderBy, Query

from shared_code.data_model.validators.is_uuid import is_uuid
from shared_code.util.time import utcnow


def safe_quoted_split(terms: str) -> t.Generator[str]:
    """Split terms on spaces except when quoted (bash-style).

    If quotes are not properly closed, `shlex` gets confused, so return the
    original string instead for strict search.
    """
    try:
        yield from shlex.split(terms)
    except ValueError:
        # shlex couldn't split, search verbatim
        yield terms


class SearchTermMode(enum.Enum):
    """Whether a parsed search term should include or exclude matches."""

    INCLUDE = "include"
    EXCLUDE = "exclude"


@dataclass(frozen=True, slots=True)
class SearchTerm:
    """A normalized search term together with its include/exclude mode."""

    part: str
    mode: SearchTermMode = SearchTermMode.INCLUDE


@dataclass(frozen=True, slots=True)
class TermSearchResult:
    """Query fragments and ranking metadata for a parsed search term."""

    query: Query
    rank_clauses: list[str]
    max_rank: int


def parsed_search_terms(terms: str) -> t.Generator[SearchTerm]:
    """Yield normalized search terms with mode metadata."""
    for term in safe_quoted_split(terms):
        if term.startswith("-") and len(term) > 1:
            mode = SearchTermMode.EXCLUDE
            term = term[1:]
        else:
            mode = SearchTermMode.INCLUDE

        if term:
            yield SearchTerm(part=term, mode=mode)


def search_for_fieldtype(field: Field, search: str) -> Query | None:
    """Build a field-type-specific query condition for a search value."""
    fieldtype = field.type

    if not fieldtype:
        return None

    if fieldtype in ("string", "text"):
        return field.contains(search)
    elif fieldtype.startswith("list:"):
        # manually use like instead of contains for partial matching:
        return field.ilike(f"%{search}%")
    elif fieldtype == "id":
        if search.isdigit():
            return field == search
        # else: can't match 'id' on non-digit
    elif isinstance(fieldtype, SQLCustomType) and fieldtype.native == "uuid":
        if is_uuid(search):
            return field == search
        # else: can't match uuid
    else:
        # fallback other types to exact match:
        return field == search

    return None


class SearchMixin(Mixin):
    """Provide search functionality within selected fields for inheriting classes.

    Usage:
        1. Inherit this mixin in a class to enable search functionality on specific fields.
        2. Define the fields to search by passing them as `search_fields` to the class declaration.

    Example:
        class MyModel(TypedTable, SearchMixin, search_fields=("name", "description")):
            ...

    Methods Provided:
        - search: Builds a query withf optional search term, ordering, and field selection.
        - _apply_orderby: Applies ordering to the query based on a specified field or random seed.
        - _apply_search: Filters results across specified search fields.

    Arguments (for subclass definition):
        search_fields: A tuple of field names (strings) that should be searchable.

    Example Query:
        MyModel.search(
            search="example term",
            order="~name",
            select=["name", "description"]
        )

    """

    __settings__: t.TypedDict(  # type: ignore
        "SearchFieldSettings",
        {
            "search_fields": tuple[str, ...],
        },
    )  # set via init subclass

    def __init_subclass__(cls, search_fields: tuple[str, ...] = (), **kw: t.Any) -> None:
        """Initialize subclass with specified search fields.

        Arguments:
            search_fields: A tuple of field names that will be included in search filters
                           for this model. These fields must be accessible in the inheriting
                           class and should support either direct equality comparison or `.contains()`.
            **kw: Additional keyword arguments forwarded to `super().__init_subclass__()`.

        Additional Configuration:
            Sets `__settings__` for the subclass, storing specified search fields to be referenced
            in the mixin's search logic.

        """
        # append settings:
        super().__init_subclass__(**kw)
        existing_settings = getattr(cls, "__settings__", None) or {}
        inherited_search_fields = existing_settings.get("search_fields", ())
        cls.__settings__ = existing_settings | {
            # inherit parent fields when subclass doesn't pass explicit search_fields
            "search_fields": search_fields or inherited_search_fields,
        }

    @classmethod
    def __search_mixin_daily_seed__(cls) -> str:
        """Return the seed that keeps the random order stable for a whole day."""
        return utcnow().strftime("%Y%m%d")  # e.g. 20240201 for 1st of Feb

    @classmethod
    def __search_mixin_random_orderby__(cls) -> str:
        """Return a deterministic 'random' order expression.

        `ORDER BY RANDOM()` cannot be used here:
        - Postgres rejects it in combination with SELECT DISTINCT (which typedal adds
          when a paginated query joins relationships), since a volatile ORDER BY
          expression can never appear in the select list.
        - It reshuffles per query, so paginating would repeat and skip rows.

        Hashing the primary key with a daily seed gives a stable shuffle that changes
        once a day, is safe to repeat in the select list, and survives pagination.
        """
        return f"md5(concat({rname(cls.id)}, '{cls.__search_mixin_daily_seed__()}'))"

    @classmethod
    def _apply_orderby[T: _TypedTable](
        cls, order: OrderBy | t.Literal["random"], builder: QueryBuilder[T]
    ) -> QueryBuilder[T]:
        """Apply an order to the query based on the specified field or order type.

        Arguments:
            order: Accepts a string, Field, or "random".
                   - "random": Applies a randomized ordering using a daily seed.
                   - String: Uses the specified field for ordering; "~" prefix reverses the order.
            builder: The query builder instance to apply the order to.

        Returns:
            The modified QueryBuilder with applied ordering.

        """
        orderby: OrderBy | t.Iterable[OrderBy] | None

        # explicitly check 'str' otherwise == 'random' becomes a Query
        if isinstance(order, str) and order == "random":
            orderby = cls.__search_mixin_random_orderby__()
        elif isinstance(order, str):
            if order.startswith("~"):
                orderby = ~cls[order[1:]]
            else:
                resolved_order = t.cast(OrderBy, cls[order])
                orderby = resolved_order
        else:
            orderby = order

        return builder.select(orderby=orderby)

    @classmethod
    def apply_orderby[T: _TypedTable](
        cls, order: OrderBy | t.Literal["random"], builder: QueryBuilder[T]
    ) -> QueryBuilder[T]:
        """Apply ordering, ignoring unknown field errors."""
        try:
            return cls._apply_orderby(order, builder)
        except KeyError:
            # field does not exist -> ignore
            return builder

    @classmethod
    def _search_field_names(cls) -> list[str]:
        """Return the ordered field names used for text search ranking."""
        return [
            "id",
            "gid",
            *cls.__settings__["search_fields"],
            "slug",
        ]

    @classmethod
    def _build_term_match(
        cls,
        part: str,
        search_fields: list[str],
        *,
        extra_conditions_fn: t.Callable[[str], t.Iterable[Query]] | None = None,
        include_ranking: bool,
    ) -> TermSearchResult:
        """Build the OR-query and ranking clauses for a single search part."""
        part_query = cls.id == 0
        rank_clauses: list[str] = []
        max_rank = len(search_fields)

        for idx, fieldname in enumerate(search_fields, 1):
            if not (field := getattr(cls, fieldname, None)):
                continue

            condition = search_for_fieldtype(field, part)
            if not condition:
                continue

            if include_ranking:
                rank_clauses.append(f"WHEN {condition} THEN {idx}")
            part_query |= condition

        if extra_conditions_fn:
            for extra_idx, condition in enumerate(extra_conditions_fn(part), start=len(search_fields) + 1):
                if include_ranking:
                    rank_clauses.append(f"WHEN {condition} THEN {extra_idx}")
                part_query |= condition
                max_rank = max(max_rank, extra_idx)

        return TermSearchResult(
            query=part_query,
            rank_clauses=rank_clauses,
            max_rank=max_rank,
        )

    @classmethod
    def _combine_search_query(
        cls,
        query: Query,
        part_query: Query,
        mode: SearchTermMode,
    ) -> Query:
        """Combine one term query into the accumulated search query."""
        return query & (~part_query if mode is SearchTermMode.EXCLUDE else part_query)

    @classmethod
    def _apply_search_orderby(
        cls,
        builder: QueryBuilder,
        rank_clauses: list[str],
        max_rank: int,
    ) -> QueryBuilder:
        """Apply search ranking and preserve existing ordering."""
        new_orderby = f"""CASE {" ".join(rank_clauses)} ELSE {max_rank + 1} END""" if rank_clauses else None

        if existing_orderby := builder.select_kwargs.get("orderby"):
            existing_orderby = rname(existing_orderby) if isinstance(existing_orderby, Field) else existing_orderby

            new_orderby = f"{new_orderby}, {existing_orderby}" if new_orderby else existing_orderby

        if new_orderby:
            return builder.select(orderby=new_orderby)

        return builder

    @classmethod
    def _apply_search(
        cls,
        search: str,
        builder: QueryBuilder,
        *,
        extra_conditions_fn: t.Callable[[str], t.Iterable[Query]] | None = None,
    ) -> QueryBuilder:
        """Apply a search filter across predefined search fields.

        Arguments:
            search: The search term to match within each field specified in __settings__.
                  Search terms are split by words unless enclosed in quotes.
                  For example: 'Machine learning "neural networks" research' will be split into
                  ['machine', 'learning', 'neural networks', 'research']
            builder: The query builder instance to apply the search filter to.
            extra_conditions_fn: Optional callback that returns additional query
                conditions for each search part.

        Returns:
            The modified QueryBuilder with search conditions applied across multiple fields.

        """
        search = (search or "").strip()
        if not search:
            return builder

        query = cls.id > 0  # Start with true condition
        search_fields = cls._search_field_names()
        rank_clauses: list[str] = []
        max_rank = len(search_fields)

        # For each search term, ensure it matches at least one field
        for search_term in parsed_search_terms(search):
            term_match = cls._build_term_match(
                search_term.part,
                search_fields,
                extra_conditions_fn=extra_conditions_fn,
                include_ranking=search_term.mode is SearchTermMode.INCLUDE,
            )
            rank_clauses.extend(term_match.rank_clauses)
            max_rank = max(max_rank, term_match.max_rank)
            query = cls._combine_search_query(query, term_match.query, search_term.mode)

        builder = cls._apply_search_orderby(builder, rank_clauses, max_rank)

        return builder.where(query)

    @classmethod
    def apply_search(cls, search: str, builder: QueryBuilder) -> QueryBuilder:
        """Apply search filtering to the provided query builder."""
        return cls._apply_search(search, builder)

    @classmethod
    def search(
        cls,
        search: str = "",
        *,
        order: OrderBy | t.Literal["random"] | None = None,
        limit: int | None = None,
        builder: QueryBuilder[t.Self] | None = None,
        select: list[str | Field] | None = None,
    ) -> QueryBuilder[t.Self]:
        """Build a search query with optional ordering and field selection.

        Arguments:
            search: A term to apply across fields specified in __settings__ for filtering results.
            order: Defines the ordering of results; accepts a field name, a Field object, or "random".
            limit: limit amount of results (you can also use .paginate on the result)
            builder: An optional QueryBuilder instance to build upon.
            select: An optional list of fields to include in the query.

        Returns:
            A QueryBuilder instance with applied search, order, and selection criteria.

        """
        builder = builder or QueryBuilder(cls)

        if select:
            builder = builder.select(*select)

        if limit:
            builder = builder.select(limitby=(0, limit))

        if order:
            builder = cls.apply_orderby(order, builder)

        search = (search or "").strip()
        if search:
            builder = cls.apply_search(search, builder)

        return builder
