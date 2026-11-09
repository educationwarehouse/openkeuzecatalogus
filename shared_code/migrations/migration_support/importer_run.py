"""View migration manager for legacy importer-run reporting schemas."""

from edwh_migrate import ViewMigrationManager

from shared_code.migrations.migration_support.product import ProductModelWithPrio_V1
from shared_code.migrations.migration_support.supplier import SupplierModelWithPrio_V1


# noinspection PyPep8Naming
class ImporterRunEventCompatibilityViews_V1(ViewMigrationManager):
    """Expose former importer result-table schemas from generic run events."""

    uses = ()

    since = "create_importer_run_event_compatibility_views_20260910_001"

    def up(self) -> None:
        """Create read-only legacy reporting views backed by importer events."""
        self.db.executesql("""
        CREATE VIEW importer_run_count_stat AS
        SELECT
            id,
            gid,
            run_gid,
            supplier_gid,
            supplier_name,
            scope_type AS count_type,
            scope_key AS count_key,
            scope_label AS count_label,
            metric,
            value,
            created_at,
            updated_at
        FROM importer_run_event
        WHERE event_type = 'metric';

        CREATE VIEW importer_run_error_stat AS
        SELECT
            id,
            gid,
            run_gid,
            supplier_gid,
            supplier_name,
            entity_type,
            entity_gid,
            entity_olid,
            entity_name,
            NULLIF(details ->> 'method_gid', '')::uuid AS method_gid,
            details ->> 'method_name' AS method_name,
            metric AS error_code,
            COALESCE((details ->> 'validation_failed')::boolean, FALSE) AS validation_failed,
            details -> 'error_details' AS error_details,
            created_at,
            updated_at
        FROM importer_run_event
        WHERE event_type = 'error';
        """)

    def down(self) -> None:
        """Drop the compatibility views before recreating them."""
        self.db.executesql("""
        DROP VIEW IF EXISTS importer_run_error_stat;
        DROP VIEW IF EXISTS importer_run_count_stat;
        """)


# noinspection PyPep8Naming
class ImporterRunNonImportedProductsReportV1(ViewMigrationManager):
    """Expose former importer result-table schemas from generic run events."""

    uses = (ProductModelWithPrio_V1,)

    since = "create_non_imported_products_report_v1_20260930_001"

    def up(self) -> None:
        """Create read-only legacy reporting views backed by importer events."""
        self.db.executesql("""
        CREATE VIEW non_imported_products_report_v1 AS
        WITH latest_run AS (
            SELECT DISTINCT ON (source, supplier_name)
                   gid
              FROM importer_run
             ORDER BY source, supplier_name, id DESC
        ),
        failed_row AS (
            SELECT e.details -> 'error_details' -> 'source_row' AS source_row,
                   e.details -> 'error_details' -> 'messages'    AS error_message
              FROM importer_run_event e
              JOIN latest_run r ON r.gid = e.run_gid
             WHERE e.entity_gid IS NULL
               AND e.details -> 'error_details' -> 'source_row' IS NOT NULL
        )
        SELECT p.isbn,
               f.source_row ->> 'productFamilyName' AS methode_name,
               f.source_row ->> 'productId'         AS product_id,
               f.source_row ->> 'publisher'         AS publisher_name,
               f.error_message
          FROM failed_row f
          LEFT JOIN product_model p ON p.isbn = f.source_row ->> 'productId';
        """)

    def down(self) -> None:
        """Drop the compatibility views before recreating them."""
        self.db.executesql("""
        DROP VIEW IF EXISTS non_imported_products_report_v1;
        """)


# noinspection PyPep8Naming
class EduVDashboardReportV1(ViewMigrationManager):
    """Expose former importer result-table schemas from generic run events."""

    uses = (ProductModelWithPrio_V1, SupplierModelWithPrio_V1)

    since = "create_edu_v_dashboard_v1_20260930_001"

    def up(self) -> None:
        """Create read-only legacy reporting views backed by importer events."""
        self.db.executesql("""
        CREATE VIEW eduv_dashboard_report_v1 AS
        WITH latest_run AS (
            SELECT DISTINCT ON (source, supplier_name)
                   gid
              FROM importer_run
             ORDER BY source, supplier_name, id DESC
        ),
        failed_row AS (
            SELECT e.details -> 'error_details' -> 'source_row' AS source_row,
                   e.details -> 'error_details' -> 'messages'    AS error_message
              FROM importer_run_event e
              JOIN latest_run r ON r.gid = e.run_gid
             WHERE e.entity_gid IS NULL
               AND e.details -> 'error_details' -> 'source_row' IS NOT NULL
        )select
            p.gid   as product_gid,
            p.isbn  as product_id,
            p.name  as product_name,
            s.name  as supplier_name,
            case
                when s.endpoint_type = 'edu-v-kennisnet-v1' then 'v1'
                when s.endpoint_type = 'edu-v-kennisnet-v2' then 'v2'
                when s.endpoint_type = 'edu-v' then
                    case
                        when s.endpoint_base_url ~* '(^|[^a-z0-9])v1([^0-9]|$)'
                         and s.endpoint_base_url ~* '(^|[^a-z0-9])v2([^0-9]|$)' then 'ambigu'
                        when s.endpoint_base_url ~* '(^|[^a-z0-9])v1([^0-9]|$)' then 'v1'
                        when s.endpoint_base_url ~* '(^|[^a-z0-9])v2([^0-9]|$)' then 'v2'
                        else 'onbekend'
                    end
            end as "edu-v-versie",
            case
                when available NOT IN ('verwijderd') then 'in-catalogus'
                when available IN ('verwijderd') then 'uit-aanlevering'
            end as "catalogus-status",
            null as error_message
        from product_model p
        join supplier_model s on p.supplier_gid = s.gid
        union all
        SELECT
               p.gid as product_gid,
               f.source_row ->> 'productId'         AS product_id,
               f.source_row ->> 'name'              AS product_name,
               f.source_row ->> 'publisher'         AS publisher_name,
               null                                 as "edu-v-versie",
               --f.source_row ->> 'productFamilyName' AS methode_name,
               'niet-in-catalogus'                  as catalogus_status,
               f.error_message
          FROM failed_row f
          LEFT JOIN product_model p ON p.isbn = f.source_row ->> 'productId';
        """)

    def down(self) -> None:
        """Drop the compatibility views before recreating them."""
        self.db.executesql("""
        DROP VIEW IF EXISTS eduv_dashboard_report_v1;
        """)
