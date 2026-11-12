"""Canonical school subject filtering over unchanged supplier values."""

import typing as t

from typedal import QueryBuilder

from shared_code.modules.school_subjects import (
    normalize_school_subject,
    preferred_spelling,
    school_subject_name_lookup,
)
from shared_code.util.queries import falsey_query

from .definitions import DynamicFieldFilterDefinition, as_flat_value_list, flatten_filter_values
from .types import CatalogFilterContext, DynamicFilterMetadata, FilterOption


class SchoolSubjectFilterDefinition(DynamicFieldFilterDefinition):
    """Group known subjects and match every original spelling in the catalogue."""

    def __init__(self, metadata: DynamicFilterMetadata, context: CatalogFilterContext) -> None:
        """Initialize lazy per-request name and raw-value lookups."""
        super().__init__(metadata, context)
        self._name_lookup: dict[str, str] | None = None
        self._aliases_by_name: dict[str, list[str]] | None = None
        self._raw_values: dict[str, list[str]] | None = None

    def name_lookup(self) -> dict[str, str]:
        """Load the normalized name and alias lookup once per request."""
        if self._name_lookup is None:
            self._name_lookup = school_subject_name_lookup()

        return self._name_lookup

    def option_value(self, value: str) -> str:
        """Return the canonical name, or a normalized unknown subject value."""
        normalized = normalize_school_subject(value)
        return self.name_lookup().get(normalized, normalized)

    def raw_values(self) -> dict[str, list[str]]:
        """Group distinct raw values without losing their whitespace or casing."""
        if self._raw_values is None:
            field = self.field
            values = self.context.option_builder.column(field, distinct=field)
            raw_values = {value for value in flatten_filter_values(values) if isinstance(value, str) and value.strip()}
            self._raw_values = {}

            for value in sorted(raw_values):
                self._raw_values.setdefault(self.option_value(value), []).append(value)

        return self._raw_values

    def parse(self) -> list[str] | None:
        """Canonicalize selected names and aliases, preserving selection order."""
        values = as_flat_value_list(self.context.params.get(self.slug))
        normalized = dict.fromkeys(self.option_value(value) for value in values if value.strip())
        return list(normalized) or None

    def counts(self, builder: QueryBuilder[t.Any]) -> dict[str, int]:
        """Count each material once per option using the same canonical groups."""
        field = self.field
        count_field = builder.model.id.count()
        rows = builder.select(field, count_field, groupby=field).execute()
        counts: dict[str, int] = {}
        for row in rows:
            values = {self.option_value(value) for value in row[field] or [] if value.strip()}
            for value in values:
                counts[value] = counts.get(value, 0) + int(row[count_field])

        return counts

    def build_options(self) -> list[FilterOption]:
        """Show one canonical option per group and retain unknown subjects."""
        options = []
        for value, raw_values in self.raw_values().items():
            label = value
            if self.name_lookup().get(normalize_school_subject(value)) != value:
                label = preferred_spelling(raw_values)
            options.append(FilterOption(value=value, label=label))

        return sorted(options, key=lambda option: option.label.casefold())

    def aliases_by_name(self) -> dict[str, list[str]]:
        """Index the normalized aliases per canonical name for option searches."""
        if self._aliases_by_name is None:
            self._aliases_by_name = {}
            for alias, name in self.name_lookup().items():
                self._aliases_by_name.setdefault(name, []).append(alias)

        return self._aliases_by_name

    def matches_option(self, option: FilterOption, query: str) -> bool:
        """Find canonical options by their supported aliases as well."""
        if super().matches_option(option, query):
            return True

        return any(query in alias for alias in self.aliases_by_name().get(option.value, []))

    def apply(self, builder: QueryBuilder[t.Any], active_value: str | list[str] | bool) -> QueryBuilder[t.Any]:
        """Expand selected groups to exact raw list entries before filtering."""
        selected = as_flat_value_list(active_value)
        if not selected:
            return builder

        raw_values = self.raw_values()
        variants = {variant for value in selected for variant in raw_values.get(self.option_value(value), [value])}
        query = falsey_query(self.field)
        for variant in sorted(variants):
            query |= self.field.contains(variant, case_sensitive=True)

        return builder.where(query)
