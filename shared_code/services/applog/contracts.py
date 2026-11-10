"""Application logging service contracts."""

import abc
import datetime as dt
import json
import logging
import typing as t
from uuid import UUID

from endow import Service
from typedal import PaginatedRows

from shared_code.util.env import bool_from_env
from shared_code.util.time import utcnow
from shared_code.util.types import Ordered

if t.TYPE_CHECKING:
    from shared_code.data_model import Method, Product
    from shared_code.infra.database import DatabaseContext
    from shared_code.modules.auth import AuthContext
    from shared_code.modules.catalog_filters import CatalogEntityKind, ResolvedCatalogFilters
    from shared_code.modules.comparison.types import VisionIds


class ApplogEvent(t.TypedDict, total=False):
    """Normalized applog event payload that can be persisted as evidence."""

    timestamp: dt.datetime | str | int
    kind: t.Literal["auth_action", "error", "event"]
    action: str | None
    details: str | dict
    user_gid: str | None
    session_gid: str | None
    related: str | UUID | None
    # ...


class AuthEvent(ApplogEvent):
    """Specialized applog event shape for authentication actions."""

    email: str | None
    success: bool | None
    ip: str | None
    user_agent: str | None


class ApplogSignal(t.TypedDict):
    """Signal envelope used for queued applog processing."""

    # not used manually

    name: str
    signal_source: str
    evidence: ApplogEvent
    session_gid: str | None
    user_gid: str | None
    ts: str
    related: str | None


def selected_extra_field(row: t.Any, field_name: str) -> t.Any | None:
    """Return a selected non-model field from a regular or joined TypedDAL row."""
    raw_rows = (getattr(row, "_row", None), *getattr(row, "_rows", ()))
    for raw_row in raw_rows:
        if raw_row is None:
            continue
        elif field_name in raw_row:
            return raw_row[field_name]
        elif field_name in raw_row.get("_extra", {}):
            return raw_row["_extra"][field_name]
    return None


class Applogger(Service, abc.ABC):
    """Abstract app logger contract with shared event helpers."""

    db: DatabaseContext
    auth: AuthContext

    @abc.abstractmethod
    def fire(self, event: ApplogEvent) -> bool:
        """Persist a normalized applog event payload."""
        ...

    def try_fire(self, event: ApplogEvent) -> bool:
        """Attempt to persist an event and swallow unexpected failures."""
        try:
            if "timestamp" not in event:
                event["timestamp"] = utcnow()
            if not event.get("session_gid"):
                event["session_gid"] = self.auth.session_gid

            delivered = self.fire(event)
            if not delivered:
                logging.error("Audit event delivery rejected: %s", event.get("action") or event.get("kind"))

            return delivered
        except Exception:
            logging.exception("Audit event delivery failed: %s", event.get("action") or event.get("kind"))
            return False

    def write_auth_event(self, event: AuthEvent) -> bool:
        """Backward-compatible auth-specific writer alias."""
        return self.try_fire(event)

    def log_catalog_search[T: Product | Method](
        self,
        entity_kind: CatalogEntityKind,
        *,
        rows: PaginatedRows[T],
        cache_hit: bool,
        filters: ResolvedCatalogFilters | None,
        dynamic_sort_ed_id: int | None,
        search_type: t.Literal["catalog", "similar"] = "catalog",
        source_gid: str | None = None,
        suggestion_limit: int | None = None,
    ) -> bool:
        """Log one catalog-result page for anonymous search analysis."""
        # Avoid importing the data-model package while this core service is initialized.
        from shared_code.data_model import SearchRankWeight
        from shared_code.data_model.mixins.search import parsed_search_terms

        active_definitions = filters.active_definitions if filters is not None else []
        active_filters = {definition.slug: value for definition, value in active_definitions}
        active_filter_ed_ids = {
            definition.slug: definition.metadata.dynamic_filter_ed_id for definition, _ in active_definitions
        }
        search_query = next(
            (
                t.cast(str, value)
                for definition, value in active_definitions
                if definition.metadata.filter_kind == "search"
            ),
            None,
        )
        pagination = rows.pagination
        if search_type == "similar":
            search_rank_weight_ed_ids = []
            score_field = "similarity_rank"
            search_context = {
                "search_type": search_type,
                "source_gid": source_gid,
                "suggestion_limit": suggestion_limit,
            }
        else:
            search_rank_weight_ed_ids = SearchRankWeight.where(SearchRankWeight.entity_kind == entity_kind).column(
                SearchRankWeight.id
            )
            score_field = "search_rank"
            search_context = {}

        result_scores = [
            {
                "id": row.id,
                "score": selected_extra_field(row, score_field),
            }
            for row in rows
        ]
        return self.try_fire(
            {
                "kind": "event",
                "action": "catalog_search",
                "details": {
                    **search_context,
                    "entity_kind": entity_kind,
                    "cache_hit": cache_hit,
                    "dynamic_sort_ed_id": dynamic_sort_ed_id,
                    "active_filters": active_filters,
                    "active_filter_ed_ids": active_filter_ed_ids,
                    "search_rank_weight_ed_ids": search_rank_weight_ed_ids,
                    "original_query": search_query,
                    "normalized_terms": [
                        {"term": term.part, "mode": term.mode.value} for term in parsed_search_terms(search_query or "")
                    ],
                    "result_count": pagination["total_items"],
                    "result_ed_ids": [row.id for row in rows],
                    "result_scores": result_scores,
                    "pagination": {
                        "current_page": pagination["current_page"],
                        "total_pages": pagination["total_pages"],
                    },
                },
            },
        )

    def log_catalog_compare(
        self,
        entity_kind: CatalogEntityKind,
        *,
        requested_gids: Ordered[str],
        rows: t.Iterable[t.Any],
        vision_ids: VisionIds,
    ) -> bool:
        """Log the requested catalogue records and their resolved revisions."""
        return self.try_fire(
            {
                "kind": "event",
                "action": "catalog_compare",
                "details": {
                    "entity_kind": entity_kind,
                    "requested_gids": list(requested_gids),
                    "result_ed_ids": [row.id for row in rows],
                    "vision_ed_ids": vision_ids,
                },
            }
        )

    def log_catalog_detail(
        self,
        entity_kind: CatalogEntityKind,
        *,
        requested_gid: str,
        row: t.Any,
        vision_ids: t.Sequence[int | None],
        referer: str | None = None,
        from_similar: bool = False,
    ) -> bool:
        """Log one successfully resolved public catalogue detail view."""
        context = {}
        if referer:
            context["referer"] = referer
        if from_similar:
            context["search_type"] = "similar"
        return self.try_fire(
            {
                "kind": "event",
                "action": "catalog_detail",
                "details": {
                    **context,
                    "entity_kind": entity_kind,
                    "requested_gid": requested_gid,
                    "result_ed_id": row.id,
                    "vision_ed_ids": list(vision_ids),
                },
            }
        )

    def refresh_catalog_search_report(self) -> None:
        """Refresh the catalog-search materialized reporting view."""
        self.db.executesql("REFRESH MATERIALIZED VIEW catalog_search_report_v1;")

    def log_auth_action(
        self,
        action: str,
        user_gid: UUID | str | None = None,
        email: str | None = None,
        success: bool | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
        details: t.Mapping[str, t.Any] | None = None,
    ) -> bool:
        """Build and persist (or enqueue) an auth action log event."""
        event = self._build_auth_event(
            action=action,
            user_gid=user_gid,
            email=email,
            success=success,
            ip=ip,
            user_agent=user_agent,
            details=details,
        )
        # Queueing belongs in a separate implementation; base contract is sync only.
        return self.try_fire(event)

    @classmethod
    def from_env(cls) -> Applogger:
        """Instantiate the configured applogger from environment settings."""
        if bool_from_env("APPLOG_FAKE", default=False):
            from .file import FileApplogger

            return FileApplogger.from_env()
        else:
            from .deque import DequeApplogger

            return DequeApplogger.from_env()

    @staticmethod
    def _build_auth_event(
        action: str,
        user_gid: UUID | str | None,
        email: str | None,
        success: bool | None,
        ip: str | None,
        user_agent: str | None,
        details: t.Mapping[str, t.Any] | None,
    ) -> AuthEvent:
        normalized_details = dict(details or {})
        return {
            "timestamp": utcnow().isoformat(),
            "kind": "auth_action",
            "action": action,
            "user_gid": str(user_gid) if user_gid else None,
            "email": email,
            "success": success,
            "ip": ip,
            "user_agent": user_agent,
            "details": json.loads(json.dumps(normalized_details, default=str)),
        }
