"""Business logic for the search-relevance editor and preview."""

import typing as t

from endow import Domain
from typedal import TypedRows

from shared_code.data_model import SearchRankWeight
from shared_code.data_model.mixins.effdt import validate_and_update_effectivedated
from shared_code.data_model.tables.search_rank_weight import SEARCH_RANK_SCORE_NAMES, SEARCH_RANK_SECTION_TITLES
from shared_code.modules.auth import AuthContext
from shared_code.services.applog.contracts import selected_extra_field

if t.TYPE_CHECKING:
    from shared_code.infra.database import DatabaseContext


SEARCH_RELEVANCE_TITLES = {"product": "Productrelevantie", "method": "Methoderelevantie"}


class RelevanceSection(t.TypedDict):
    """One ordered group of relevance rules for the tuning page."""

    key: str
    title: str
    rules: list[SearchRankWeight]


class RelevancePreviewResult(t.TypedDict):
    """A catalogue row and its calculated relevance score."""

    name: str
    score: int


class SearchRelevance(Domain):
    """Load, preview, and persist product and method relevance settings."""

    db: DatabaseContext
    auth: AuthContext

    def sections(self, entity_kind: str) -> list[RelevanceSection]:
        """Return relevance rules grouped in their configured display order."""
        rules_by_section = {key: [] for key in SEARCH_RANK_SECTION_TITLES}
        for rule in self._rules(entity_kind):
            rules_by_section[rule.section].append(rule)

        return [
            {"key": key, "title": title, "rules": rules_by_section[key]}
            for key, title in SEARCH_RANK_SECTION_TITLES.items()
            if rules_by_section[key]
        ]

    def preview(self, entity_kind: str, query: str, values: t.Mapping[str, str]) -> list[RelevancePreviewResult]:
        """Run a relevance-ranked preview using submitted but unsaved score values."""
        table = self.db.find_model(entity_kind)
        assert table, f"unknown table '{entity_kind}'"
        query = query.strip()
        if not query:
            return []

        rules = self._rules(entity_kind)
        score_overrides = self._score_overrides(rules, values)
        builder = table.where(table.available != "verwijderd").select(table.ALL)
        rows = table._apply_search(query, builder, score_overrides=score_overrides).paginate(page=1, limit=3)
        return [{"name": str(row.name), "score": int(selected_extra_field(row, "search_rank") or 0)} for row in rows]

    def save(self, entity_kind: str, values: t.Mapping[str, str]) -> None:
        """Persist score values using the data-model validators."""
        if not (self.auth.is_service() or self.auth.is_admin()):
            raise PermissionError("Only admins and services may save search relevance ranking")

        try:
            for rule in self._rules(entity_kind):
                scores = {
                    score_name: values[f"{rule.gid}-{score_name}"]
                    for score_name in SEARCH_RANK_SCORE_NAMES
                    if f"{rule.gid}-{score_name}" in values
                }
                if not scores:
                    continue
                _, errors = validate_and_update_effectivedated(SearchRankWeight, rule, **scores)
                if errors:
                    raise ValueError(next(iter(errors.values())))
        except ValueError as e:
            self.db.rollback()
            raise e
        self.db.commit()

    @staticmethod
    def _rules(entity_kind: str) -> TypedRows[SearchRankWeight]:
        """Load the configured rules for one supported catalogue entity."""
        return (
            SearchRankWeight.where(SearchRankWeight.entity_kind == entity_kind)
            .select(orderby=(SearchRankWeight.section, SearchRankWeight.sort_order, SearchRankWeight.id))
            .collect()
        )

    @staticmethod
    def _score_overrides(
        rules: t.Iterable[SearchRankWeight],
        values: t.Mapping[str, str],
    ) -> dict[str, dict[str, int | None]]:
        """Convert submitted numeric score values into transient ranking overrides."""
        overrides: dict[str, dict[str, int | None]] = {}
        for rule in rules:
            rule_gid = rule.gid
            for score_name in SEARCH_RANK_SCORE_NAMES:
                if (key := f"{rule_gid}-{score_name}") in values:
                    value = values[key]
                    overrides.setdefault(rule_gid, {})[score_name] = int(value) if value else None
        return overrides
