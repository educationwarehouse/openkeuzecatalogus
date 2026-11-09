"""Versioned reporting contract for importer warning events."""

from edwh_migrate import ViewMigrationManager


# noinspection PyPep8Naming
class ImporterRunWarningReport_V1(ViewMigrationManager):
    """Expose warning events for SQL reporting."""

    uses = ()
    since = "backfill_importer_run_warnings_20261006_001"

    def up(self) -> None:
        """Create a stable SQL interface for warning reporting."""
        self.db.executesql("""
            CREATE VIEW importer_run_warning_stat AS
            SELECT e.run_gid,
                   e.metric AS warning_code,
                   e.details ->> 'message' AS message,
                   COALESCE(e.details ->> 'product_name', e.entity_name) AS product_name,
                   e.details ->> 'reason' AS reason,
                   e.details ->> 'source_url' AS source_url,
                   e.supplier_gid,
                   e.supplier_name,
                   e.entity_type,
                   e.entity_gid,
                   e.entity_olid,
                   e.details
            FROM importer_run_event e
            WHERE e.event_type = 'warning';
        """)

    def down(self) -> None:
        """Drop the reporting interface before recreating it."""
        self.db.executesql("DROP VIEW IF EXISTS importer_run_warning_stat;")
