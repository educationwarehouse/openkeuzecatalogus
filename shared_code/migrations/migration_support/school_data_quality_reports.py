"""View migration managers for school data-quality reports."""

import os

from edwh_migrate import ViewMigrationManager

from .organisation import OrganisationModelWithPrio_V1
from .tagged import TaggedModelWithPrio_V1


def platform_base_url() -> str:
    """Build the public platform URL at view-definition time."""
    hosting_domain = os.environ["HOSTINGDOMAIN"].rstrip("/")
    subdomain = os.environ.get("PY4WEB_SUBDOMAIN", "").strip(".")
    hostname = f"{subdomain}.{hosting_domain}" if subdomain else hosting_domain
    return f"https://{hostname}"


# noinspection PyPep8Naming
class LocationsWithoutOrganisationMappingReport_V1(ViewMigrationManager):
    """Manage the report of locations without a school mapping."""

    uses = (OrganisationModelWithPrio_V1, TaggedModelWithPrio_V1)

    since = "create_locations_without_organisation_mapping_report_20260713_001"

    def up(self) -> None:
        """Create the report view."""
        base_url = platform_base_url()
        self.db.executesql(
            f"""
            CREATE VIEW locations_without_organisation_mapping_report_v1 AS
            WITH location_schools AS (
                SELECT DISTINCT ON (school_location.object_gid)
                       school_location.object_gid AS location_gid,
                       school.gid AS school_gid
                FROM tagged_model AS school_location
                JOIN organisation_model AS school
                  ON school.gid = school_location.subject_gid
                WHERE school_location.predicate = 'IS_SCHOOL_OF'
                ORDER BY school_location.object_gid, school.gid
            ), valid_location_mappings AS (
                SELECT DISTINCT school_location.object_gid AS location_gid
                FROM tagged_model AS school_location
                JOIN organisation_model AS school
                  ON school.gid = school_location.subject_gid
                JOIN tagged_model AS board_school
                  ON board_school.object_gid = school.gid
                 AND board_school.predicate = 'IS_BOARD_OF'
                JOIN organisation_model AS board
                  ON board.gid = board_school.subject_gid
                WHERE school_location.predicate = 'IS_SCHOOL_OF'
            )
            SELECT location.gid AS location_gid,
                   location.name AS location_name,
                   location.brin,
                   location.vestigingscode,
                   location.city,
                   CASE
                       WHEN location_schools.school_gid IS NULL THEN '#'
                       ELSE FORMAT('{base_url}/admin/school/%s/locations/edit/%s', location_schools.school_gid, location.gid)
                   END AS fix_url
            FROM organisation_model AS location
            LEFT JOIN location_schools
              ON location_schools.location_gid = location.gid
            LEFT JOIN valid_location_mappings
              ON valid_location_mappings.location_gid = location.gid
            WHERE location.organisation_type = 'location'
              AND valid_location_mappings.location_gid IS NULL;
            """,  # noqa S608: base_url is in our control
        )

    def down(self) -> None:
        """Drop the report view before its source models are rebuilt."""
        self.db.executesql("DROP VIEW IF EXISTS locations_without_organisation_mapping_report_v1;")


# noinspection PyPep8Naming
class LocationsWithoutBrinVestCodeReport_V1(ViewMigrationManager):
    """Manage the report of locations without a BRIN-location code."""

    uses = (OrganisationModelWithPrio_V1, TaggedModelWithPrio_V1)

    since = "create_locations_without_brin_vest_code_report_20260713_002"

    def up(self) -> None:
        """Create the report view."""
        base_url = platform_base_url()
        self.db.executesql(
            f"""
            CREATE VIEW locations_without_brin_vest_code_report_v1 AS
            WITH location_schools AS (
                SELECT DISTINCT ON (school_location.object_gid)
                       school_location.object_gid AS location_gid,
                       school.gid AS school_gid
                FROM tagged_model AS school_location
                JOIN organisation_model AS school
                  ON school.gid = school_location.subject_gid
                WHERE school_location.predicate = 'IS_SCHOOL_OF'
                ORDER BY school_location.object_gid, school.gid
            )
            SELECT location.gid AS location_gid,
                   location.name AS location_name,
                   location.brin,
                   location.vestigingscode,
                   location.city,
                   CASE
                       WHEN location_schools.school_gid IS NULL THEN '#'
                       ELSE FORMAT('{base_url}/admin/school/%s/locations/edit/%s', location_schools.school_gid, location.gid)
                   END AS fix_url
            FROM organisation_model AS location
            LEFT JOIN location_schools
              ON location_schools.location_gid = location.gid
            WHERE location.organisation_type = 'location'
              AND (
                  NULLIF(BTRIM(location.brin), '') IS NULL
                  OR NULLIF(BTRIM(location.vestigingscode), '') IS NULL
              );
            """,  # noqa S608: base_url is in our control
        )

    def down(self) -> None:
        """Drop the report view before its source model is rebuilt."""
        self.db.executesql("DROP VIEW IF EXISTS locations_without_brin_vest_code_report_v1;")


# noinspection PyPep8Naming
class SchoolsWithoutHomepageUrlReport_V1(ViewMigrationManager):
    """Manage the report of schools without a homepage URL."""

    uses = (OrganisationModelWithPrio_V1, TaggedModelWithPrio_V1)

    since = "create_schools_without_homepage_url_report_20260713_003"

    until = "add_vestigingscode_to_school_data_quality_reports_20260716_002"

    def up(self) -> None:
        """Create the report view."""
        base_url = platform_base_url()
        self.db.executesql(
            f"""
            CREATE VIEW schools_without_homepage_url_report_v1 AS
            WITH school_boards AS (
                SELECT DISTINCT ON (board_school.object_gid)
                       board_school.object_gid AS school_gid,
                       board.gid AS board_gid
                FROM tagged_model AS board_school
                JOIN organisation_model AS board
                  ON board.gid = board_school.subject_gid
                WHERE board_school.predicate = 'IS_BOARD_OF'
                ORDER BY board_school.object_gid, board.gid
            )
            SELECT school.gid AS school_gid,
                   school.name AS school_name,
                   school.brin,
                   school.city,
                   CASE
                       WHEN school_boards.board_gid IS NULL THEN '#'
                       ELSE FORMAT('{base_url}/admin/board/%s/schools/edit/%s', school_boards.board_gid, school.gid)
                   END AS fix_url
            FROM organisation_model AS school
            LEFT JOIN school_boards
              ON school_boards.school_gid = school.gid
            WHERE school.organisation_type = 'school'
              AND NULLIF(BTRIM(school.website), '') IS NULL;
            """,  # noqa S608: base_url is in our control
        )

    def down(self) -> None:
        """Drop the report view before its source model is rebuilt."""
        self.db.executesql("DROP VIEW IF EXISTS schools_without_homepage_url_report_v1;")


# noinspection PyPep8Naming
class SchoolsWithoutHomepageUrlReport_V1b(ViewMigrationManager):
    """Manage the homepage report with a vestigingscode column."""

    uses = (OrganisationModelWithPrio_V1, TaggedModelWithPrio_V1)

    since = "add_vestigingscode_to_school_data_quality_reports_20260716_002"

    def up(self) -> None:
        """Create the report view."""
        base_url = platform_base_url()
        self.db.executesql(
            f"""
            CREATE VIEW schools_without_homepage_url_report_v1 AS
            WITH school_boards AS (
                SELECT DISTINCT ON (board_school.object_gid)
                       board_school.object_gid AS school_gid,
                       board.gid AS board_gid
                FROM tagged_model AS board_school
                JOIN organisation_model AS board
                  ON board.gid = board_school.subject_gid
                WHERE board_school.predicate = 'IS_BOARD_OF'
                ORDER BY board_school.object_gid, board.gid
            )
            SELECT school.gid AS school_gid,
                   school.name AS school_name,
                   school.brin,
                   school.vestigingscode,
                   school.city,
                   CASE
                       WHEN school_boards.board_gid IS NULL THEN '#'
                       ELSE FORMAT('{base_url}/admin/board/%s/schools/edit/%s', school_boards.board_gid, school.gid)
                   END AS fix_url
            FROM organisation_model AS school
            LEFT JOIN school_boards
              ON school_boards.school_gid = school.gid
            WHERE school.organisation_type = 'school'
              AND NULLIF(BTRIM(school.website), '') IS NULL;
            """,  # noqa S608: base_url is in our control
        )

    def down(self) -> None:
        """Drop the report view before its source model is rebuilt."""
        self.db.executesql("DROP VIEW IF EXISTS schools_without_homepage_url_report_v1;")


# noinspection PyPep8Naming
class SchoolsWithoutEmailDomainReport_V1(ViewMigrationManager):
    """Manage the report of schools without an email domain."""

    uses = (OrganisationModelWithPrio_V1, TaggedModelWithPrio_V1)

    since = "create_schools_without_email_domain_report_20260713_004"

    until = "add_vestigingscode_to_school_data_quality_reports_20260716_002"

    def up(self) -> None:
        """Create the report view."""
        base_url = platform_base_url()
        self.db.executesql(
            f"""
            CREATE VIEW schools_without_email_domain_report_v1 AS
            WITH school_boards AS (
                SELECT DISTINCT ON (board_school.object_gid)
                       board_school.object_gid AS school_gid,
                       board.gid AS board_gid
                FROM tagged_model AS board_school
                JOIN organisation_model AS board
                  ON board.gid = board_school.subject_gid
                WHERE board_school.predicate = 'IS_BOARD_OF'
                ORDER BY board_school.object_gid, board.gid
            )
            SELECT school.gid AS school_gid,
                   school.name AS school_name,
                   school.brin,
                   school.city,
                   CASE
                       WHEN school_boards.board_gid IS NULL THEN '#'
                       ELSE FORMAT('{base_url}/admin/board/%s/schools/edit/%s', school_boards.board_gid, school.gid)
                   END AS fix_url
            FROM organisation_model AS school
            LEFT JOIN school_boards
              ON school_boards.school_gid = school.gid
            WHERE school.organisation_type = 'school'
              AND COALESCE(NULLIF(BTRIM(school.email_domains), ''), '||') = '||';
            """,  # noqa S608: base_url is in our control
        )

    def down(self) -> None:
        """Drop the report view before its source model is rebuilt."""
        self.db.executesql("DROP VIEW IF EXISTS schools_without_email_domain_report_v1;")


# noinspection PyPep8Naming
class SchoolsWithoutEmailDomainReport_V1b(ViewMigrationManager):
    """Manage the email-domain report with a vestigingscode column."""

    uses = (OrganisationModelWithPrio_V1, TaggedModelWithPrio_V1)

    since = "add_vestigingscode_to_school_data_quality_reports_20260716_002"

    def up(self) -> None:
        """Create the report view."""
        base_url = platform_base_url()
        self.db.executesql(
            f"""
            CREATE VIEW schools_without_email_domain_report_v1 AS
            WITH school_boards AS (
                SELECT DISTINCT ON (board_school.object_gid)
                       board_school.object_gid AS school_gid,
                       board.gid AS board_gid
                FROM tagged_model AS board_school
                JOIN organisation_model AS board
                  ON board.gid = board_school.subject_gid
                WHERE board_school.predicate = 'IS_BOARD_OF'
                ORDER BY board_school.object_gid, board.gid
            )
            SELECT school.gid AS school_gid,
                   school.name AS school_name,
                   school.brin,
                   school.vestigingscode,
                   school.city,
                   CASE
                       WHEN school_boards.board_gid IS NULL THEN '#'
                       ELSE FORMAT('{base_url}/admin/board/%s/schools/edit/%s', school_boards.board_gid, school.gid)
                   END AS fix_url
            FROM organisation_model AS school
            LEFT JOIN school_boards
              ON school_boards.school_gid = school.gid
            WHERE school.organisation_type = 'school'
              AND COALESCE(NULLIF(BTRIM(school.email_domains), ''), '||') = '||';
            """,  # noqa S608: base_url is in our control
        )

    def down(self) -> None:
        """Drop the report view before its source model is rebuilt."""
        self.db.executesql("DROP VIEW IF EXISTS schools_without_email_domain_report_v1;")
