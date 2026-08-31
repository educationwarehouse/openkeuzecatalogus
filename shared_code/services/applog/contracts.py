"""Application logging service contracts."""

import abc
import datetime as dt
import json
import typing as t
from uuid import UUID

from endow import Service
from typedal import PaginatedRows

from shared_code.util.env import bool_from_env
from shared_code.util.time import utcnow

if t.TYPE_CHECKING:
    from shared_code.data_model import Method, Product
    from shared_code.infra.database import DatabaseContext
    from shared_code.modules.catalog_filters import CatalogEntityKind, ResolvedCatalogFilters


class ApplogEvent(t.TypedDict, total=False):
    """Normalized applog event payload that can be persisted as evidence."""

    timestamp: dt.datetime | str | int
    kind: t.Literal["auth_action", "error", "event"]
    action: str | None
    details: str | dict
    user_gid: str | None
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


class Applogger(Service, abc.ABC):
    """Abstract app logger contract with shared event helpers."""

    db: DatabaseContext

    @abc.abstractmethod
    def fire(self, event: ApplogEvent) -> bool:
        """Persist a normalized applog event payload."""
        ...

    def try_fire(self, event: ApplogEvent) -> bool:
        """Attempt to persist an event and swallow unexpected failures."""
        try:
            if "timestamp" not in event:
                event["timestamp"] = utcnow()
            return self.fire(event)
        except Exception as e:
            print(f"[applog] failed with {e}")
            return False

    def write_auth_event(self, event: AuthEvent) -> bool:
        """Backward-compatible auth-specific writer alias."""
        return self.try_fire(event)

    def log_catalog_search(
        self,
        entity_kind: CatalogEntityKind,
        *,
        rows: PaginatedRows[Product | Method],
        filters: ResolvedCatalogFilters | None,
    ) -> bool:
        """Log one catalog-result page for anonymous search analysis."""
        # Avoid importing the data-model package while this core service is initialized.
        from shared_code.data_model.mixins.search import parsed_search_terms

        active_definitions = filters.active_definitions if filters is not None else []
        active_filters = {definition.slug: value for definition, value in active_definitions}
        search_query = next(
            (
                t.cast(str, value)
                for definition, value in active_definitions
                if definition.metadata.filter_kind == "search"
            ),
            None,
        )
        pagination = rows.pagination
        return self.try_fire(
            {
                "kind": "event",
                "action": "catalog_search",
                "details": {
                    "entity_kind": entity_kind,
                    "active_filters": active_filters,
                    "original_query": search_query,
                    "normalized_terms": [
                        {"term": term.part, "mode": term.mode.value} for term in parsed_search_terms(search_query or "")
                    ],
                    "result_count": pagination["total_items"],
                    "result_ed_ids": [row.id for row in rows],
                    "pagination": {
                        "current_page": pagination["current_page"],
                        "total_pages": pagination["total_pages"],
                    },
                },
            },
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
        if bool_from_env("APPLOG_FAKE", False):
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
