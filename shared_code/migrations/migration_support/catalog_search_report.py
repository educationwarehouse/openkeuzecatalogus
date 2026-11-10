"""View migration manager for the catalog-search reporting view."""

from edwh_migrate import ViewMigrationManager


# noinspection PyPep8Naming
class CatalogSearchReport_V1(ViewMigrationManager):
    """Manage the materialized report of catalog search activity."""

    uses = ()

    since = "create_catalog_search_report_20260713_005"

    until = "convert_catalog_search_report_active_filters_to_jsonb_20260716_001"

    def up(self) -> None:
        """Create the export-oriented catalog search report."""
        self.db.executesql("""
        CREATE MATERIALIZED VIEW catalog_search_report_v1 AS
        SELECT
            signal.id AS signal_id,
            signal.ts,
            evidence.source -> 'details' ->> 'entity_kind' AS entity_kind,
            evidence.source -> 'details' ->> 'original_query' AS original_query,
            evidence.source -> 'details' -> 'normalized_terms' AS normalized_terms,
            evidence.source -> 'details' -> 'active_filters' AS active_filters,
            (evidence.source -> 'details' ->> 'result_count')::integer AS result_count,
            evidence.source -> 'details' -> 'result_ed_ids' AS result_ed_ids,
            (evidence.source -> 'details' -> 'pagination' ->> 'current_page')::integer AS current_page,
            (evidence.source -> 'details' -> 'pagination' ->> 'total_pages')::integer AS total_pages
        FROM signal
        INNER JOIN evidence ON evidence.id = signal.evidence_id
        WHERE evidence.source ->> 'action' = 'catalog_search';

        CREATE UNIQUE INDEX catalog_search_report_v1_signal_id_index
            ON catalog_search_report_v1 (signal_id);
        CREATE INDEX catalog_search_report_v1_ts_index
            ON catalog_search_report_v1 (ts DESC);
        """)

    def down(self) -> None:
        """Drop the report before rebuilding it."""
        self.db.executesql("DROP MATERIALIZED VIEW IF EXISTS catalog_search_report_v1;")


# noinspection PyPep8Naming
class CatalogSearchReport_V1b(ViewMigrationManager):
    """Manage the catalog-search report with JSONB active filters."""

    uses = ()

    since = "convert_catalog_search_report_active_filters_to_jsonb_20260716_001"

    until = "add_catalog_search_result_scores_20260721_002"

    def up(self) -> None:
        """Create the export-oriented catalog search report."""
        self.db.executesql("""
        CREATE MATERIALIZED VIEW catalog_search_report_v1 AS
        SELECT
            signal.id AS signal_id,
            signal.ts,
            evidence.source -> 'details' ->> 'entity_kind' AS entity_kind,
            evidence.source -> 'details' ->> 'original_query' AS original_query,
            evidence.source -> 'details' -> 'normalized_terms' AS normalized_terms,
            (evidence.source -> 'details' -> 'active_filters')::jsonb AS active_filters,
            (evidence.source -> 'details' ->> 'result_count')::integer AS result_count,
            evidence.source -> 'details' -> 'result_ed_ids' AS result_ed_ids,
            (evidence.source -> 'details' -> 'pagination' ->> 'current_page')::integer AS current_page,
            (evidence.source -> 'details' -> 'pagination' ->> 'total_pages')::integer AS total_pages
        FROM signal
        INNER JOIN evidence ON evidence.id = signal.evidence_id
        WHERE evidence.source ->> 'action' = 'catalog_search';

        CREATE UNIQUE INDEX catalog_search_report_v1_signal_id_index
            ON catalog_search_report_v1 (signal_id);
        CREATE INDEX catalog_search_report_v1_ts_index
            ON catalog_search_report_v1 (ts DESC);
        """)

    def down(self) -> None:
        """Drop the report before rebuilding it."""
        self.db.executesql("DROP MATERIALIZED VIEW IF EXISTS catalog_search_report_v1;")


# noinspection PyPep8Naming
class CatalogSearchReport_V1c(ViewMigrationManager):
    """Manage the catalog-search report with displayed relevance scores."""

    uses = ()

    since = "add_catalog_search_result_scores_20260721_002"

    def up(self) -> None:
        """Create the export-oriented catalog search report."""
        self.db.executesql("""
        CREATE MATERIALIZED VIEW catalog_search_report_v1 AS
        SELECT
            signal.id AS signal_id,
            signal.ts,
            evidence.source -> 'details' ->> 'entity_kind' AS entity_kind,
            evidence.source -> 'details' ->> 'original_query' AS original_query,
            evidence.source -> 'details' -> 'normalized_terms' AS normalized_terms,
            (evidence.source -> 'details' -> 'active_filters')::jsonb AS active_filters,
            (evidence.source -> 'details' ->> 'result_count')::integer AS result_count,
            evidence.source -> 'details' -> 'result_ed_ids' AS result_ed_ids,
            evidence.source -> 'details' -> 'result_scores' AS result_scores,
            (evidence.source -> 'details' -> 'pagination' ->> 'current_page')::integer AS current_page,
            (evidence.source -> 'details' -> 'pagination' ->> 'total_pages')::integer AS total_pages
        FROM signal
        INNER JOIN evidence ON evidence.id = signal.evidence_id
        WHERE evidence.source ->> 'action' = 'catalog_search';

        CREATE UNIQUE INDEX catalog_search_report_v1_signal_id_index
            ON catalog_search_report_v1 (signal_id);
        CREATE INDEX catalog_search_report_v1_ts_index
            ON catalog_search_report_v1 (ts DESC);
        """)

    def down(self) -> None:
        """Drop the report before rebuilding it."""
        self.db.executesql("DROP MATERIALIZED VIEW IF EXISTS catalog_search_report_v1;")


# noinspection PyPep8Naming
class CatalogSearchReport_V1d(ViewMigrationManager):
    """Manage the catalog-search report with session and login state."""

    uses = ()

    since = "add_catalog_search_session_gid_20260825_001"
    until = "add_catalog_search_recommendation_context_20261005_002"

    def up(self) -> None:
        """Create the export-oriented catalog search report."""
        self.db.executesql("""
        CREATE MATERIALIZED VIEW catalog_search_report_v1 AS
        SELECT
            signal.id AS signal_id,
            signal.ts,
            signal.session_gid,
            signal.user_gid IS NOT NULL AS is_logged_in,
            evidence.source -> 'details' ->> 'entity_kind' AS entity_kind,
            evidence.source -> 'details' ->> 'original_query' AS original_query,
            evidence.source -> 'details' -> 'normalized_terms' AS normalized_terms,
            (evidence.source -> 'details' -> 'active_filters')::jsonb AS active_filters,
            (evidence.source -> 'details' ->> 'result_count')::integer AS result_count,
            evidence.source -> 'details' -> 'result_ed_ids' AS result_ed_ids,
            evidence.source -> 'details' -> 'result_scores' AS result_scores,
            (evidence.source -> 'details' -> 'pagination' ->> 'current_page')::integer AS current_page,
            (evidence.source -> 'details' -> 'pagination' ->> 'total_pages')::integer AS total_pages
        FROM signal
        INNER JOIN evidence ON evidence.id = signal.evidence_id
        WHERE evidence.source ->> 'action' = 'catalog_search';

        CREATE UNIQUE INDEX catalog_search_report_v1_signal_id_index
            ON catalog_search_report_v1 (signal_id);
        CREATE INDEX catalog_search_report_v1_ts_index
            ON catalog_search_report_v1 (ts DESC);
        """)

    def down(self) -> None:
        """Drop the report before rebuilding it."""
        self.db.executesql("DROP MATERIALIZED VIEW IF EXISTS catalog_search_report_v1;")


# noinspection PyPep8Naming
class CatalogSearchReport_V1e(ViewMigrationManager):
    """Distinguish catalogue searches from recommendation impressions."""

    uses = ()

    since = "add_catalog_search_recommendation_context_20261005_002"

    def up(self) -> None:
        """Rebuild the report with backward-compatible recommendation context."""
        self.db.executesql("""
        CREATE MATERIALIZED VIEW catalog_search_report_v1 AS
        SELECT
            signal.id AS signal_id,
            signal.ts,
            signal.session_gid,
            signal.user_gid IS NOT NULL AS is_logged_in,
            evidence.source -> 'details' ->> 'entity_kind' AS entity_kind,
            evidence.source -> 'details' ->> 'original_query' AS original_query,
            evidence.source -> 'details' -> 'normalized_terms' AS normalized_terms,
            (evidence.source -> 'details' -> 'active_filters')::jsonb AS active_filters,
            (evidence.source -> 'details' ->> 'result_count')::integer AS result_count,
            evidence.source -> 'details' -> 'result_ed_ids' AS result_ed_ids,
            evidence.source -> 'details' -> 'result_scores' AS result_scores,
            (evidence.source -> 'details' -> 'pagination' ->> 'current_page')::integer AS current_page,
            (evidence.source -> 'details' -> 'pagination' ->> 'total_pages')::integer AS total_pages,
            COALESCE(evidence.source -> 'details' ->> 'search_type', 'catalog') AS search_type,
            evidence.source -> 'details' ->> 'source_gid' AS source_gid,
            (evidence.source -> 'details' ->> 'suggestion_limit')::integer AS suggestion_limit
        FROM signal
        INNER JOIN evidence ON evidence.id = signal.evidence_id
        WHERE evidence.source ->> 'action' = 'catalog_search';

        CREATE UNIQUE INDEX catalog_search_report_v1_signal_id_index
            ON catalog_search_report_v1 (signal_id);
        CREATE INDEX catalog_search_report_v1_ts_index
            ON catalog_search_report_v1 (ts DESC);
        """)

    def down(self) -> None:
        """Drop the existing report before rebuilding it."""
        self.db.executesql("DROP MATERIALIZED VIEW catalog_search_report_v1;")
