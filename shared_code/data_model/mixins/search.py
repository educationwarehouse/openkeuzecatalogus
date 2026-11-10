"""Search helpers and mixin utilities for typedal models."""

import enum
import shlex
import typing as t
import unicodedata
from dataclasses import dataclass

from pydal.helpers.classes import SQLCustomType
from pydal.objects import Expression
from typedal import QueryBuilder
from typedal.fields import Field, TypedField, rname
from typedal.mixins import Mixin
from typedal.tables import TypedTable, _TypedTable
from typedal.types import OrderBy, Query

from shared_code.data_model.validators.is_uuid import is_uuid
from shared_code.util.time import utcnow

# note: Keep this equal to PostgreSQL's `pg_trgm.similarity_threshold`. To change it,
#  add a migration that runs `ALTER ROLE CURRENT_USER SET # pg_trgm.similarity_threshold TO <new value>`
#  so every new application database connection uses the threshold read by the index-supported `%` operator.
TRIGRAM_SIMILARITY_THRESHOLD = 0.30


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


@dataclass(frozen=True, slots=True)
class SearchRankRule:
    """One fully configured source of weighted search matches."""

    name: str
    conditions_for_part: t.Callable[[str], tuple[SearchRankCondition, ...]]

    def group_for_part(self, part: str) -> SearchRankGroup:
        """Build this rule's strongest-match group for one parsed search part."""
        return SearchRankGroup(self.conditions_for_part(part))


@dataclass(frozen=True, slots=True)
class SearchRankCondition:
    """One weighted condition within a ranked field match."""

    query: Query
    score: int


@dataclass(frozen=True, slots=True)
class SearchRankGroup:
    """Conditions for one field, scored only by its strongest matching rule."""

    conditions: tuple[SearchRankCondition, ...]

    @property
    def query(self) -> Query | None:
        """Return the combined condition used to include a matching row."""
        query: Query | None = None
        for condition in self.conditions:
            query = condition.query if query is None else query | condition.query
        return query

    def score_expression(self) -> str:
        """Return SQL that awards only the highest matching score for this field."""
        ordered_conditions = sorted(self.conditions, key=lambda condition: condition.score, reverse=True)
        cases = " ".join(f"WHEN {condition.query} THEN {condition.score}" for condition in ordered_conditions)
        return f"CASE {cases} ELSE 0 END"


def basic_search_query(search: str, table: t.Any) -> Query:
    """Build a basic text-search query for a table without specialised search."""
    query = table.id > 0

    for term in parsed_search_terms(search):
        term_query = table.id == 0
        for field in table:
            if field.readable and (condition := search_for_fieldtype(field, term.part, allow_exact_match=False)):
                term_query |= condition

        query &= ~term_query if term.mode is SearchTermMode.EXCLUDE else term_query

    return query


def apply_basic_search[T: TypedTable](search: str, table: type[T], builder: QueryBuilder[T]) -> QueryBuilder[T]:
    """Filter a typed table by readable text fields when it has no specialised search."""
    return builder.where(basic_search_query(search, table))


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


def escape_sql_like_value(value: str) -> str:
    """Escape literal characters that have special meaning in SQL LIKE patterns."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def normalize_search_value(value: str) -> str:
    """Remove accents from a search value to match PostgreSQL's `unaccent` output."""
    return "".join(char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char))


def unaccent(field: Field | Expression) -> Expression:
    """Wrap a field in PostgreSQL's `unaccent` function."""

    def _unaccent(value: Field | Expression, query_env: dict[str, t.Any] | None = None) -> str:
        return f"unaccent({value._dialect.expand(value, query_env=query_env or {})})"

    return Expression(field.db, _unaccent, field, type=field.type)


def _search_text_field(field: Field, search: str) -> Query:
    """Apply accent-insensitive matching on PostgreSQL text fields."""
    db = field.db
    assert db, "field must have db"
    adapter = db._adapter
    assert adapter, "db must have adapter"
    if adapter.dbengine == "postgres":
        return unaccent(field.cast("text")).contains(normalize_search_value(search))
    else:
        return field.contains(search)


def _search_exact_field(field: Field, search: str, allow_exact_match: bool) -> Query | None:
    """Validate identifiers before matching and optionally match other types exactly."""
    fieldtype = field.type
    if fieldtype == "id":
        if search.isdigit():
            return field == search
    elif isinstance(fieldtype, SQLCustomType) and fieldtype.native == "uuid":
        if is_uuid(search):
            return field == search
    elif allow_exact_match:
        return field == search
    return None


def search_for_fieldtype(field: Field, search: str, allow_exact_match: bool = True) -> Query | None:
    """Build a field-type-specific query condition for a search value."""
    fieldtype = field.type

    if not fieldtype:
        return None

    if fieldtype in ("string", "text"):
        return _search_text_field(field, search)
    elif isinstance(fieldtype, str) and fieldtype.startswith("list:"):
        # manually use like instead of contains for partial matching:
        return field.ilike(f"%{search}%")
    else:
        return _search_exact_field(field, search, allow_exact_match)


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
        extra_conditions_fn: t.Callable[[str], t.Iterable[Query]] | None = None,
        include_ranking: bool = False,
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
        extra_conditions_fn: t.Callable[[str], t.Iterable[Query]] | None = None,
    ) -> QueryBuilder:
        """Apply the legacy field-order search ranking."""
        search = (search or "").strip()
        if not search:
            return builder

        query = cls.id > 0  # start with true condition
        search_fields = cls._search_field_names()
        rank_clauses: list[str] = []
        max_rank = len(search_fields)
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

        return cls._apply_search_orderby(builder, rank_clauses, max_rank).where(query)

    @classmethod
    def apply_search(cls, search: str, builder: QueryBuilder) -> QueryBuilder:
        """Apply a table's configured text search to the provided builder."""
        return cls._apply_search(search, builder)

    @classmethod
    def search(
        cls,
        search: str = "",
        order: OrderBy | t.Literal["random"] | None = None,
        limit: int | None = None,
        builder: QueryBuilder[t.Self] | None = None,
        select: list[str | Field] | None = None,
    ) -> QueryBuilder[t.Self]:
        """Build a search query with optional ordering, limit, and selected fields."""
        builder = builder or QueryBuilder(cls)
        if select:
            builder = builder.select(*select)
        if limit:
            builder = builder.select(limitby=(0, limit))

        if order:
            builder = cls.apply_orderby(order, builder)
        return cls.apply_search(search, builder) if (search or "").strip() else builder


class RankedSearchMixin(SearchMixin):
    """Add configurable weighted relevance ranking to :class:`SearchMixin`."""

    @classmethod
    def search_rank_rules(
        cls,
        score_overrides: dict[str, dict[str, int | None]] | None = None,
    ) -> tuple[SearchRankRule, ...]:
        """Build ranking rules from the persisted configuration for this table."""
        from shared_code.data_model.tables.search_rank_weight import SearchRankWeight

        entity_kind = cls.__name__.lower()
        rows = SearchRankWeight.where(SearchRankWeight.entity_kind == entity_kind).collect()
        rules: list[SearchRankRule] = []
        for row in rows:
            scores = score_overrides.get(row.gid, {}) if score_overrides else {}
            if row.related_table:
                related_table = cls.id.db.find_model(row.related_table)
                if related_table is None or row.foreign_key is None or row.related_key is None:
                    raise ValueError(f"Invalid related search ranking rule: {row.label}")
                rules.append(
                    cls.related_search_rank_rule(
                        row.key,
                        getattr(cls, row.foreign_key),
                        related_table=related_table,
                        related_key=getattr(related_table, row.related_key),
                        related_field=getattr(related_table, row.source_field),
                        exact=scores.get("exact", row.exact),
                        prefix=scores.get("prefix", row.prefix),
                        contains=scores.get("contains", row.contains),
                        trigram=scores.get("trigram", row.trigram),
                    )
                )
            else:
                rules.append(
                    cls.direct_search_rank_rule(
                        row.key,
                        getattr(cls, row.source_field),
                        exact=scores.get("exact", row.exact),
                        prefix=scores.get("prefix", row.prefix),
                        contains=scores.get("contains", row.contains),
                        trigram=scores.get("trigram", row.trigram),
                    )
                )
        return tuple(rules)

    @staticmethod
    def _trigram_condition(field: Field | TypedField[t.Any], part: str, threshold: float) -> Query:
        """Return a safely quoted, index-supported PostgreSQL trigram condition."""
        if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
            raise ValueError("trigram threshold must be between 0 and 1")
        if threshold != TRIGRAM_SIMILARITY_THRESHOLD:
            raise ValueError("trigram threshold must match TRIGRAM_SIMILARITY_THRESHOLD")
        assert field.db, "Can't continue without db"
        value = field.db._adapter.represent(part, "string")
        return Query(field.db, f"CAST({rname(field)} AS text) % CAST({value} AS text)")

    @classmethod
    def direct_search_rank_rule(
        cls,
        name: str,
        field: Field | TypedField[t.Any],
        exact: int | None = None,
        prefix: int | None = None,
        contains: int | None = None,
        trigram: int | None = None,
        trigram_threshold: float = TRIGRAM_SIMILARITY_THRESHOLD,
    ) -> SearchRankRule:
        """Build a complete direct-field rule that can score every search part."""

        def conditions_for_part(part: str) -> tuple[SearchRankCondition, ...]:
            conditions: list[SearchRankCondition] = []
            literal_part = escape_sql_like_value(part)
            if exact is not None:
                conditions.append(SearchRankCondition(field.ilike(literal_part, escape="\\"), exact))
            if prefix is not None:
                conditions.append(SearchRankCondition(field.ilike(f"{literal_part}%", escape="\\"), prefix))
            if contains is not None:
                conditions.append(SearchRankCondition(field.contains(part), contains))
            if trigram is not None and " " not in part:
                conditions.append(SearchRankCondition(cls._trigram_condition(field, part, trigram_threshold), trigram))
            return tuple(conditions)

        return SearchRankRule(name=name, conditions_for_part=conditions_for_part)

    @classmethod
    def related_search_rank_rule(
        cls,
        name: str,
        foreign_key: Field | TypedField[t.Any],
        *,
        related_table: type[TypedTable],
        related_key: Field | TypedField[t.Any],
        related_field: Field | TypedField[t.Any],
        exact: int | None = None,
        prefix: int | None = None,
        contains: int | None = None,
        trigram: int | None = None,
        trigram_threshold: float = TRIGRAM_SIMILARITY_THRESHOLD,
        # todo: also make trigram_threshold configurable in UI?
    ) -> SearchRankRule:
        """Build a complete related-field rule that can score every search part."""
        direct_rule = cls.direct_search_rank_rule(
            name,
            related_field,
            exact=exact,
            prefix=prefix,
            contains=contains,
            trigram=trigram,
            trigram_threshold=trigram_threshold,
        )

        def conditions_for_part(part: str) -> tuple[SearchRankCondition, ...]:
            return tuple(
                SearchRankCondition(
                    foreign_key.belongs(related_table.where(condition.query).select(related_key).to_sql()),
                    condition.score,
                )
                for condition in direct_rule.conditions_for_part(part)
            )

        return SearchRankRule(name=name, conditions_for_part=conditions_for_part)

    @classmethod
    def _apply_ranked_search_orderby(cls, builder: QueryBuilder, rank_expression: str) -> QueryBuilder:
        """Select and order by the computed rank while preserving deterministic ties."""
        existing_orderby = builder.select_kwargs.get("orderby")
        assert cls._db, "Ranked search requires a defined database table."
        # like % should not be interpreted as %s formatted string in expression:
        rank_orderby = ~cls._db.sql_expression(rank_expression.replace("%", "%%"), output_type="integer")
        if isinstance(existing_orderby, (tuple, list)):
            orderby = (rank_orderby, *existing_orderby)
        elif existing_orderby:
            orderby = (rank_orderby, existing_orderby)
        else:
            orderby = rank_orderby
        default_fields = (cls.ALL,) if not builder.select_args else ()
        return builder.select(
            *default_fields,
            f"({rank_expression}) AS search_rank",
            orderby=t.cast(OrderBy | t.Iterable[OrderBy], orderby),
        )

    @classmethod
    def _ranked_term_query(
        cls,
        term_query: Query,
        search_term: SearchTerm,
        rank_rules: tuple[SearchRankRule, ...],
        rank_expressions: list[str],
    ) -> Query:
        """Combine a term's ranked field matches and retain scores for include terms."""
        for rank_rule in rank_rules:
            group = rank_rule.group_for_part(search_term.part)
            if group_query := group.query:
                term_query |= group_query
                if search_term.mode is SearchTermMode.INCLUDE:
                    rank_expressions.append(group.score_expression())
        return term_query

    @classmethod
    def _apply_search(
        cls,
        search: str,
        builder: QueryBuilder,
        extra_conditions_fn: t.Callable[[str], t.Iterable[Query]] | None = None,
        score_overrides: dict[str, dict[str, int | None]] | None = None,
    ) -> QueryBuilder:
        """Filter and score rows, summing strongest per-field matches for include terms."""
        search = (search or "").strip()
        if not search:
            return builder

        query = cls.id > 0  # start with true condition
        rank_rules = cls.search_rank_rules(score_overrides=score_overrides)
        rank_expressions: list[str] = []
        for search_term in parsed_search_terms(search):
            term_query = cls.id == 0
            # gid is a technical identifier, not relevance-ranked text. Keep an
            # exact gid lookup available even when no configurable rule covers it.
            if is_uuid(search_term.part):
                term_query |= cls.gid == search_term.part

            if extra_conditions_fn:
                for condition in extra_conditions_fn(search_term.part):
                    term_query |= condition

            term_query = cls._ranked_term_query(term_query, search_term, rank_rules, rank_expressions)
            query = cls._combine_search_query(query, term_query, search_term.mode)

        rank_expression = " + ".join(rank_expressions) or "0"
        return cls._apply_ranked_search_orderby(builder, rank_expression).where(query)
