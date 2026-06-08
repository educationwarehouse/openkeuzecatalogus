"""Search helpers and mixin utilities for typedal models."""

import shlex
import typing as t

from pydal.helpers.classes import SQLCustomType
from typedal import QueryBuilder
from typedal.fields import Field
from typedal.mixins import Mixin
from typedal.tables import _TypedTable
from typedal.types import OrderBy, Query

from shared_code.data_model.validators.is_uuid import is_uuid
from shared_code.services.time.clock import utcnow


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
        """Use this as a raw field in `.select()`.

        setseed expects a number between -1 and 1.
        This function converts the current date to a number in that range.
        This will break in the year 20000 but who cares.
        """
        today = utcnow()
        today = int(today.strftime("%Y%m%d"))  # e.g. 20240201 for 1st of Feb
        seed = today / 100_000_000  # range of -1 to 1
        return f"setseed({seed})"

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

        extra_fields = []
        if order == "random":
            orderby = "<random>"
            seed = cls.__search_mixin_daily_seed__()
            extra_fields.append(seed)
        elif isinstance(order, str):
            if order.startswith("~"):
                orderby = ~cls[order[1:]]
            else:
                resolved_order = t.cast(OrderBy, cls[order])
                orderby = resolved_order
        else:
            orderby = order

        return builder.select(*extra_fields, orderby=orderby)

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

        search_fields = [
            "id",
            "gid",
            *cls.__settings__["search_fields"],
            "slug",
        ]

        orderby = []
        max_rank = len(search_fields)
        search_parts = safe_quoted_split(search)

        # For each search term, ensure it matches at least one field
        for part in search_parts:
            part_query = cls.id == 0  # Start with false for this search term

            for idx, fieldname in enumerate(search_fields, 1):
                if not (field := getattr(cls, fieldname, None)):
                    # can't search through fields we don't have eh?
                    continue

                # build query part specifically for this field's type:
                if condition := search_for_fieldtype(field, part):
                    # note: both condition (Query) and idx (int) are controlled values from code, not user input,
                    #  so no query injection risk here
                    orderby.append(f"WHEN {condition} THEN {idx}")
                    part_query |= condition  # This term matches if found in ANY field

            if extra_conditions_fn:
                for extra_idx, condition in enumerate(extra_conditions_fn(part), start=len(search_fields) + 1):
                    # note: both condition (Query) and idx (extra_idx) are controlled values from code, not user input,
                    #  so no query injection risk here
                    orderby.append(f"WHEN {condition} THEN {extra_idx}")
                    part_query |= condition
                    max_rank = max(max_rank, extra_idx)

            # All search terms must be satisfied (AND across terms)
            query &= part_query

        new_orderby = f"""CASE {" ".join(orderby)} ELSE {max_rank + 1} END""" if orderby else None

        if existing_orderby := builder.select_kwargs.get("orderby"):
            new_orderby = f"{new_orderby}, {existing_orderby}" if new_orderby else existing_orderby

        if new_orderby:
            builder = builder.select(orderby=new_orderby)

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
            builder = cls.select(limitby=(0, limit))

        if order:
            builder = cls.apply_orderby(order, builder)

        search = (search or "").strip()
        if search:
            builder = cls.apply_search(search, builder)

        return builder
