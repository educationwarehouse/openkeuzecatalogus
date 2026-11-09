"""Migration manager for the location product-usage reporting view."""

from edwh_migrate import ViewMigrationManager

from .decision_team import DecisionTeamModelWithPrio_V1
from .learning_material import LearningMaterial_V1


# noinspection PyPep8Naming
class LocationProductUsageReport_V1(ViewMigrationManager):
    """Aggregate decision-process material selections by location and product."""

    uses = (DecisionTeamModelWithPrio_V1, LearningMaterial_V1)

    since = "create_location_product_usage_report_20260917_002"

    def up(self) -> None:
        """Create the live dashboard and administration reporting view."""
        self.db.executesql("""
        CREATE VIEW location_product_usage_report_v1 AS
        WITH selection_context AS (
            SELECT selection.gid AS selection_gid,
                   team.location_gid,
                   selection.olid AS product_olid,
                   selection.name AS selection_name,
                   selection.material_type,
                   team.gid AS team_gid,
                   team.name AS team_name,
                   process.gid AS process_gid,
                   process.schoolyear,
                   process.process_stage,
                   process.active,
                   material.gid AS catalog_gid,
                   material.origin AS catalog_origin,
                   material.name AS catalog_name,
                   CASE
                       WHEN selection.olid IS NULL THEN 'name:' || selection.name
                       ELSE 'olid:' || selection.olid
                   END AS product_key
            FROM decision_material_selection AS selection
            JOIN decision_process AS process
              ON process.gid = selection.process_gid
            JOIN decision_team_model AS team
              ON team.gid = process.team_gid
            LEFT JOIN learning_material AS material
              ON material.olid = selection.olid
        ), aggregated AS (
            SELECT (ARRAY_AGG(selection_gid ORDER BY selection_gid))[1] AS gid,
                   location_gid,
                   COALESCE(MAX(catalog_name), MIN(selection_name)) AS product_name,
                   MAX(product_olid) AS product_olid,
                   CONCAT(
                       '|', ARRAY_TO_STRING(ARRAY_AGG(DISTINCT material_type ORDER BY material_type), '|'), '|'
                   ) AS material_types,
                   CONCAT('|', ARRAY_TO_STRING(ARRAY_AGG(DISTINCT team_gid ORDER BY team_gid), '|'), '|')
                       AS team_gids,
                   CONCAT('|', ARRAY_TO_STRING(ARRAY_AGG(DISTINCT team_name ORDER BY team_name), '|'), '|')
                       AS team_names,
                   CONCAT('|', ARRAY_TO_STRING(ARRAY_AGG(DISTINCT process_gid ORDER BY process_gid), '|'), '|')
                       AS process_gids,
                   CONCAT('|', ARRAY_TO_STRING(ARRAY_AGG(DISTINCT schoolyear ORDER BY schoolyear), '|'), '|')
                       AS schoolyears,
                   CONCAT(
                       '|', ARRAY_TO_STRING(ARRAY_AGG(DISTINCT process_stage ORDER BY process_stage), '|'), '|'
                   ) AS process_stages,
                   COUNT(DISTINCT process_gid) FILTER (WHERE active)::integer AS active_process_count,
                   COUNT(DISTINCT process_gid) FILTER (WHERE NOT active)::integer AS archived_process_count,
                   COUNT(DISTINCT process_gid)::integer AS process_count,
                   (
                       ARRAY_AGG(catalog_gid ORDER BY catalog_gid)
                           FILTER (WHERE catalog_gid IS NOT NULL)
                   )[1] AS catalog_gid,
                   MAX(catalog_origin) AS catalog_origin
            FROM selection_context
            GROUP BY location_gid, product_key
        )
        SELECT ROW_NUMBER() OVER (ORDER BY location_gid, product_name, product_olid) AS id,
               gid,
               location_gid,
               product_name,
               product_olid,
               material_types,
               team_gids,
               team_names,
               process_gids,
               schoolyears,
               process_stages,
               active_process_count,
               archived_process_count,
               process_count,
               catalog_gid,
               catalog_origin
        FROM aggregated;
        """)

    def down(self) -> None:
        """Drop the report before rebuilding a dependency."""
        self.db.executesql("DROP VIEW IF EXISTS location_product_usage_report_v1;")
