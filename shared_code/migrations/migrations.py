"""Registered database migrations."""

import datetime as dt
import json
import os
import typing as t
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import requests
from edwh_auth_rbac import migrations as _rbac_migrations  # noqa F401 - importing exposes these migrations
from edwh_migrate import migration
from pgskewer import migrations as _pgskewer_migrations  # noqa F401 - importing exposes these migrations
from typedal import TypeDAL

from shared_code.migrations.migration_support import (
    CatalogFavoriteModelWithPrio_V1,
    DecisionProcessNoteModelWithPrio_V1,
    DecisionTeamModelWithPrio_V1,
    DynamicFilterModelWithPrio_V1,
    DynamicSortModelWithPrio_V1,
    ImporterRunEventCompatibilityViews_V1,
    LearningMaterial_V1,
    MethodModelWithPrio_V1,
    OrganisationModelWithPrio_V1,
    ProductModelWithPrio_V1,
    SearchRankWeightModelWithPrio_V1,
    SupplierModelWithPrio_V1,
    TaggedModelWithPrio_V1,
    VisionModelWithPrio_V1,
    VisionThemeDefinitionModelWithPrio_V1,
    convert_to_effdt_v1,
    no_triggers,
    rebuild_all_materialized_tables_v1,
)
from shared_code.migrations.migration_support.catalog_search_report import (
    CatalogSearchReport_V1,
    CatalogSearchReport_V1b,
    CatalogSearchReport_V1c,
    CatalogSearchReport_V1d,
    CatalogSearchReport_V1e,
)
from shared_code.migrations.migration_support.importer_run import (
    EduVDashboardReportV1,
    ImporterRunNonImportedProductsReportV1,
)
from shared_code.migrations.migration_support.importer_run_warnings import ImporterRunWarningReport_V1
from shared_code.migrations.migration_support.location_product_usage_report import LocationProductUsageReport_V1
from shared_code.migrations.migration_support.olid import backfill_collision_resistant_olids_v1
from shared_code.migrations.migration_support.organisation import (
    backfill_organisation_rbac_identities_v1,
    backfill_organisation_rbac_permissions_v1,
    backfill_organisation_rbac_permissions_v2,
)
from shared_code.migrations.migration_support.school_data_quality_reports import (
    LocationsWithoutBrinVestCodeReport_V1,
    LocationsWithoutOrganisationMappingReport_V1,
    SchoolsWithoutEmailDomainReport_V1,
    SchoolsWithoutEmailDomainReport_V1b,
    SchoolsWithoutHomepageUrlReport_V1,
    SchoolsWithoutHomepageUrlReport_V1b,
)
from shared_code.migrations.migration_support.seeding import import_seed_relationships_v1, import_seed_table_v1
from shared_code.modules.faq import parse_faq_seed
from shared_code.util.email import email_domain_sql_v1
from shared_code.util.olid import generate, generate_supplier_olid

state_of_development = os.getenv("STATE_OF_DEVELOPMENT", "ONT").upper()
seed_catalog_configuration = os.getenv("MIGRATE_SEED_CATALOG_CONFIGURATION", "").strip() == "1"
CACHE_USES_POSTGRES = "postgres" in {name.strip().lower() for name in os.getenv("CACHE_BACKEND", "").split(",")}


@migration()
def enable_pg_trgm_and_unaccent_20060000_001(db: TypeDAL) -> bool:
    """Enable PostgreSQL trigram similarity for relevance-ranked search."""
    db.executesql("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    db.executesql("CREATE EXTENSION IF NOT EXISTS unaccent;")
    db.commit()
    return True


@migration()
def create_utcnow_helper_20060000_001(db: TypeDAL) -> bool:
    """Adds a database helper function `utcnow` for Postgres."""
    db.executesql("""
                  CREATE FUNCTION utcnow() RETURNS timestamp AS
                  $$
                  SELECT NOW() AT TIME ZONE 'utc';
                  $$ LANGUAGE sql;
                  """)
    db.commit()
    return True


@migration
def create_materialized_view_meta_view_20260423_002(db: TypeDAL) -> bool:
    """Create `materialized_views` with the following columns.

    `mview` (schema.name),
    `refresh` (last file mtime),
    `is_concurrent` (has unique index),
    `is_populated` (contains data).
    """
    db.executesql(
        """
        CREATE OR REPLACE VIEW materialized_views(mview, refresh, is_concurrent, is_populated) AS
            WITH pgdata AS (SELECT pg_settings.setting AS path
                                FROM pg_settings
                                WHERE pg_settings.name = 'data_directory')
               , path AS (SELECT CASE
                                     WHEN pgdata_1.separator = '/' THEN '/'
                                     ELSE ''
                                     END AS separator
                              FROM (SELECT SUBSTR(pgdata_2.path, 1, 1) AS separator
                                        FROM pgdata pgdata_2) pgdata_1)
               , mviews AS (SELECT (ns.nspname || '.' || c.relname)                                                              AS mview
                                 , (PG_STAT_FILE((pgdata.path || path.separator) ||
                                                 PG_RELATION_FILEPATH((ns.nspname || '.' || c.relname)::regclass))).modification AS refresh
                                 , c.oid                                                                                         AS mview_oid
                                 , c.relispopulated                                                                              AS is_populated
                                FROM                       pgdata
                                   ,                       path
                                   , pg_class              c
                                         JOIN pg_namespace ns ON c.relnamespace = ns.oid
                                WHERE c.relkind = 'm')
               , unique_indexes AS (SELECT i.indrelid             AS mview_oid
                                         , BOOL_OR(i.indisunique) AS has_unique_index
                                        FROM pg_index          i
                                                 JOIN pg_class idx ON i.indexrelid = idx.oid
                                        WHERE idx.relkind = 'i' -- Indexes only
                                        GROUP BY i.indrelid)
            SELECT m.mview
                 , m.refresh
                 , COALESCE(ui.has_unique_index, FALSE) AS is_concurrent_refreshable
                 , m.is_populated
                FROM mviews                       m
                         LEFT JOIN unique_indexes ui ON m.mview_oid = ui.mview_oid;
        """,  # noqa E501
    )

    db.commit()
    return True


@migration()
def create_product_ed_20260519_001(db: TypeDAL) -> bool:
    """Create and initialize the `product_ed` effective-dated source table, and `product_model` calculated table."""
    with ProductModelWithPrio_V1(db):
        db.executesql("""
                      -- auto-generated definition
                      CREATE TABLE product_ed (
                                                  id                    serial PRIMARY KEY,
                                                  gid                   uuid NOT NULL DEFAULT uuidv4(),
                                                  isbn                  varchar(20),
                                                  name                  varchar(255),
                                                  method_gid            uuid NOT NULL,
                                                  supplier_gid          uuid NOT NULL,
                                                  levels                text,
                                                  subjects              text,
                                                  image_url             varchar(500),
                                                  description           text,
                                                  available             varchar(255),
                                                  edition               integer,
                                                  authors               text,
                                                  language              varchar(100),
                                                  license_duration      varchar(255),
                                                  level_x_year          text,
                                                  sample_copies_link    varchar(500),
                                                  more_information      varchar(500),
                                                  recommended_price     numeric(10, 2),
                                                  physical_digital_mix  varchar(255),
                                                  digital_folio_mix     text,
                                                  browser               text,
                                                  devices               text,
                                                  operating_systems     text,
                                                  elo_integration       text,
                                                  weight                numeric(8, 2),
                                                  dimensions            varchar(100),
                                                  demo_environment_link varchar(500),
                                                  olid                  varchar(255),
                                                  created_at            timestamp     DEFAULT CURRENT_TIMESTAMP,
                                                  updated_at            timestamp     DEFAULT CURRENT_TIMESTAMP,
                                                  priority              integer       DEFAULT 0,
                                                  composition           varchar(10)   DEFAULT 'single',
                                                  tto                   boolean,
                                                  bouw                  varchar(50)   DEFAULT '||',
                                                  effdt                 timestamp     DEFAULT utcnow(),
                                                  effstatus             boolean       DEFAULT TRUE,
                                                  prio                  integer       DEFAULT 0,
                                                  last_saved_by         varchar,
                                                  sync_gid              uuid          DEFAULT uuidv7() NOT NULL
                                                      CONSTRAINT product_ed_unique_sync_gid
                                                          UNIQUE,
                                                  import_error_codes    text
                                              );

                      CREATE INDEX product_ed_id_effdt
                          ON product_ed (gid ASC, effdt DESC, id ASC);

                      CREATE INDEX idx_product_ed_effdt_lookup
                          ON product_ed (effdt DESC, gid ASC, prio DESC, effdt DESC) INCLUDE (id);
                      """)
    db.commit()
    return True


@migration()
def create_supplier_ed_20260521_001(db: TypeDAL) -> bool:
    """Create and initialize the `supplier_ed` source table and model view."""
    with SupplierModelWithPrio_V1(db):
        db.executesql("""
                      -- auto-generated definition
                      CREATE TABLE supplier_ed (
                                                   id             serial
                                                       PRIMARY KEY,
                                                   gid            uuid NOT NULL DEFAULT uuidv4(),
                                                   name           varchar(255),
                                                   logo_url       varchar(500),
                                                   olid           varchar(255),
                                                   created_at     timestamp     DEFAULT CURRENT_TIMESTAMP,
                                                   updated_at     timestamp     DEFAULT CURRENT_TIMESTAMP,
                                                   status_visions varchar(25)
                                                                                DEFAULT 'nog niet gedeeld',
                                                   effdt          timestamp     DEFAULT utcnow(),
                                                   effstatus      boolean       DEFAULT TRUE,
                                                   prio           integer       DEFAULT 0,
                                                   last_saved_by  varchar,
                                                   sync_gid       uuid          DEFAULT uuidv7() NOT NULL
                                                       CONSTRAINT supplier_ed_unique_sync_gid
                                                           UNIQUE
                                               );

                      CREATE INDEX supplier_ed_id_effdt
                          ON supplier_ed (gid ASC, effdt DESC, id ASC);

                      CREATE INDEX idx_supplier_ed_effdt_lookup
                          ON supplier_ed (effdt DESC, gid ASC, prio DESC, effdt DESC) INCLUDE (id);


                      """)

    db.commit()
    return True


@migration()
def create_method_ed_20260521_001(db: TypeDAL) -> bool:
    """Create and initialize the `method_ed` source table and model view."""
    with MethodModelWithPrio_V1(db):
        db.executesql("""
                      -- auto-generated definition
                      CREATE TABLE method_ed (
                                                 id                          serial PRIMARY KEY,
                                                 gid                         uuid NOT NULL DEFAULT uuidv4(),
                                                 name                        varchar(255),
                                                 supplier_gid                uuid NOT NULL,
                                                 image_url                   varchar(500),
                                                 levels                      text,
                                                 subjects                    text,
                                                 description                 text,
                                                 available                   varchar(255),
                                                 edition                     integer,
                                                 authors                     text,
                                                 language                    varchar(100),
                                                 license_duration            varchar(255),
                                                 more_information            varchar(500),
                                                 guide_price                 numeric(10, 2),
                                                 physical_digital_mix        varchar(255),
                                                 digital_folio_mix           text,
                                                 browser                     text,
                                                 devices                     text,
                                                 operating_systems           text,
                                                 elo_integration             text,
                                                 sample_copies               varchar(255),
                                                 preview_digital_environment varchar(500),
                                                 olid                        varchar(255),
                                                 created_at                  timestamp     DEFAULT CURRENT_TIMESTAMP,
                                                 updated_at                  timestamp     DEFAULT CURRENT_TIMESTAMP,
                                                 priority                    integer       DEFAULT 0,
                                                 tto                         boolean,
                                                 bouw                        varchar(50)   DEFAULT '||',
                                                 effdt                       timestamp     DEFAULT utcnow(),
                                                 effstatus                   boolean       DEFAULT TRUE,
                                                 prio                        integer       DEFAULT 0,
                                                 last_saved_by               varchar,
                                                 sync_gid                    uuid          DEFAULT uuidv7() NOT NULL
                                                     CONSTRAINT method_ed_unique_sync_gid
                                                         UNIQUE,
                                                 import_error_codes          text
                                             );

                      CREATE INDEX method_ed_id_effdt
                          ON method_ed (gid ASC, effdt DESC, id ASC);

                      CREATE INDEX idx_method_ed_effdt_lookup
                          ON method_ed (effdt DESC, gid ASC, prio DESC, effdt DESC) INCLUDE (id);


                      """)

    db.commit()
    return True


@migration()
def create_vision_ed_20260525_001(db: TypeDAL) -> bool:
    """Create and initialize the `vision_ed` source table and model view."""
    with VisionModelWithPrio_V1(db):
        db.executesql("""
                      -- auto-generated definition
                      CREATE TABLE vision_ed (
                                                 id                 serial PRIMARY KEY,
                                                 gid                uuid      DEFAULT uuidv4()   NOT NULL,
                                                 olid               varchar(100),
                                                 onderwijskwaliteit varchar(100),
                                                 visie              text,
                                                 effdt              timestamp DEFAULT utcnow(),
                                                 effstatus          boolean   DEFAULT TRUE,
                                                 prio               integer   DEFAULT 0,
                                                 last_saved_by      varchar,
                                                 created_at         timestamp DEFAULT CURRENT_TIMESTAMP,
                                                 updated_at         timestamp DEFAULT CURRENT_TIMESTAMP,
                                                 sync_gid           uuid      DEFAULT uuidv7()   NOT NULL
                                                     CONSTRAINT vision_ed_unique_sync_gid
                                                         UNIQUE,
                                                 property_bag       json      DEFAULT '{}'::json NOT NULL
                                             );

                      CREATE INDEX idx_vision_ed_effdt_lookup
                          ON vision_ed (effdt DESC, gid ASC, prio DESC, effdt DESC) INCLUDE (id);

                      CREATE INDEX vision_ed_id_effdt
                          ON vision_ed (gid ASC, effdt DESC, id ASC);
                      """)

    db.commit()
    return True


@migration()
def seed_data_from_old_server_json_20260526_001(db: TypeDAL) -> bool:
    """Load optional seed rows from JSON endpoints and upsert by `sync_gid`."""
    base_url = os.getenv("MIGRATE_SEED_BASE_URL", "")
    if state_of_development == "TEST":
        if not seed_catalog_configuration:
            return True
        if urlsplit(base_url).scheme != "file":
            raise ValueError("MIGRATE_SEED_BASE_URL must use a file:// URL during tests")

    if not base_url:
        print("[migrate] missing MIGRATE_SEED_BASE_URL; skipping seed migration")
        return True

    with no_triggers(db), requests.Session() as session:
        for table_name in ("product_ed", "supplier_ed", "method_ed", "vision_ed"):
            import_seed_table_v1(db, base_url=base_url, table_name=table_name, session=session)

    rebuild_all_materialized_tables_v1(db)

    db.commit()
    return True


@migration()
def create_auth_user_20260528_001(db: TypeDAL) -> bool:
    """Create the initial `auth_user` table and supporting unique index."""
    db.executesql("""
                  -- auto-generated definition
                  CREATE TABLE auth_user (
                                             id                   serial PRIMARY KEY,
                                             first_name           varchar(512)            NOT NULL,
                                             last_name            varchar(512)            NOT NULL,
                                             email                varchar(512)            NOT NULL,
                                             password             varchar(512)            NOT NULL,
                                             sso_id               varchar(512),
                                             action_token         varchar(512),
                                             last_password_change timestamp,
                                             registration_key     varchar(512),
                                             reset_password_key   varchar(512),
                                             registration_id      varchar(512),
                                             onderwijs_rol        varchar(512),
                                             onderwijs_rol_anders varchar(512),
                                             onderwijs_sector     varchar(512),
                                             gid                  uuid,
                                             past_passwords_hash  text DEFAULT '||'::text NOT NULL,
                                             api_key_hash         varchar(64)
                                         );

                  ALTER TABLE auth_user
                      OWNER TO postgres;

                  CREATE UNIQUE INDEX auth_user_api_key_hash_unique
                      ON auth_user (api_key_hash)
                      WHERE (api_key_hash IS NOT NULL);
                  """)

    db.commit()
    return True


@migration()
def add_auth_user_reset_password_expires_at_20260602_001(db: TypeDAL) -> bool:
    """Add expiry tracking for password reset links."""
    db.executesql("""
                  ALTER TABLE auth_user
                      ADD COLUMN reset_password_expires_at timestamp;
                  """)

    db.commit()
    return True


@migration
def setup_required_auth_rbac_groups_20240527_001(db: TypeDAL) -> bool:
    """Ensure required default RBAC groups exist for users and admins."""
    from edwh_auth_rbac import AuthRbac

    rbac = AuthRbac(db)
    rbac.define_model(allowed_types=["user", "group"], redefine=True, migrate=False)

    db.identity.truncate()

    # all users:
    users = rbac.add_group("users@internal", "Users", [])

    # admin users:
    rbac.add_group("admin@internal", "Admins", [users])
    # users that may access the catalogue:
    # rbac.add_group("demo@internal", "Catalogue Demo Users", [users])

    db.commit()
    return True


@migration()
def add_applog_statistics_tables_20260601_001(db: TypeDAL) -> bool:
    """Create applog statistics tables and core indexes, aligned with ontwikkelstraat."""
    db.executesql(
        """
        CREATE TABLE IF NOT EXISTS public.evidence
        (
            id          serial PRIMARY KEY,
            gid         uuid,
            session_gid uuid,
            source      json,
            sha1_digest varchar(40)
        );

        CREATE TABLE IF NOT EXISTS public.signal
        (
            id           serial PRIMARY KEY,
            gid          uuid,
            ts           timestamp,
            name         varchar(512),
            source       varchar(40),
            session_gid  uuid,
            user_gid     uuid,
            evidence_id  integer REFERENCES public.evidence ON DELETE CASCADE,
            evidence_gid uuid,
            related      uuid
        );

        CREATE TABLE IF NOT EXISTS public.counts_per_minute
        (
            id           serial PRIMARY KEY,
            gid          uuid,
            ts           timestamp,
            name         varchar(512),
            evidence_id  integer REFERENCES public.evidence ON DELETE CASCADE,
            evidence_gid uuid,
            count        integer
        );

        CREATE INDEX IF NOT EXISTS evidence_sha1_digest_index
            ON public.evidence (sha1_digest ASC);
        CREATE INDEX IF NOT EXISTS evidence_source_gid
            ON public.evidence ((source ->> 'gid'));

        CREATE INDEX IF NOT EXISTS idx_signal_ts
            ON public.signal (ts DESC);
        CREATE INDEX IF NOT EXISTS idx_signal_source_name_ts
            ON public.signal (source, name, ts DESC);
        CREATE INDEX IF NOT EXISTS idx_signal_related
            ON public.signal (related);
        CREATE INDEX IF NOT EXISTS idx_signal_user_gid
            ON public.signal (user_gid);
        CREATE INDEX IF NOT EXISTS idx_signal_session_gid
            ON public.signal (session_gid);
        CREATE INDEX IF NOT EXISTS idx_signal_evidence_id
            ON public.signal (evidence_id);

        CREATE INDEX IF NOT EXISTS idx_counts_per_minute_ts
            ON public.counts_per_minute (ts DESC);
        CREATE INDEX IF NOT EXISTS idx_counts_per_minute_name_ts
            ON public.counts_per_minute (name, ts DESC);
        """,
    )
    db.commit()
    return True


@migration()
def add_endpoint_fields_to_supplier(db: TypeDAL) -> bool:
    """Add external supplier fields.

    Adds:
    - email_domain: used for automatic RBAC role assignment for new users.
    - endpoint_type: marks whether the supplier has an Edu-V endpoint or no endpoint.
    - endpoint_base_url: base URL used for external data imports, without resource paths like /products.
    """
    with SupplierModelWithPrio_V1(db):
        db.executesql("""
                      ALTER TABLE supplier_ed
                          ADD COLUMN email_domain      varchar(255),
                          ADD COLUMN endpoint_type     varchar(32) NOT NULL DEFAULT 'none',
                          ADD COLUMN endpoint_base_url varchar(512);
                      """)

        db.commit()
        return True


# todo: add rbac group for each supplier
# todo: add SIVON and Education Warehouse as suppliers with 'admin' group relation


@migration()
def setup_supplier_rbac_groups_20260618_002(db: TypeDAL) -> bool:
    """Seed special suppliers and backfill per-supplier RBAC groups."""
    from edwh_auth_rbac import AuthRbac

    rbac = AuthRbac(db)
    rbac.define_model(allowed_types=["user", "group"], redefine=True, migrate=False)

    supplier_role = rbac.add_group("supplier@internal", "Suppliers", [], allow_existing=True)

    admin_suppliers = {
        "7e9de1e0-ccc2-47e4-9d67-4c8c28d8d657": {
            "name": "Education Warehouse",
            "email_domain": "educationwarehouse.nl",
        },
        "fed7d467-849f-4134-af92-7b7d4959de0f": {
            "name": "SIVON",
            "email_domain": "sivon.nl",
        },
    }

    for gid, supplier in admin_suppliers.items():
        existing = db.executesql(
            """
            SELECT 1
                FROM supplier_model
                WHERE LOWER(email_domain) = %(email_domain)s
                LIMIT 1
            """,
            placeholders={"email_domain": supplier["email_domain"]},
        )
        if existing:
            continue

        db.executesql(
            """
            INSERT INTO supplier_ed (gid, name, olid, email_domain, endpoint_type)
                VALUES (%(gid)s, %(name)s, %(olid)s, %(email_domain)s, 'none')
            """,
            placeholders={
                "gid": gid,
                "name": supplier["name"],
                "olid": generate_supplier_olid(gid),
                "email_domain": supplier["email_domain"],
            },
        )

    # backfill rbac groups:

    for supplier in db.executesql(
        """
            SELECT gid, name, email_domain
                FROM supplier_model
                ORDER BY id
            """,
        colnames=("gid", "name", "email_domain"),
    ):
        rbac.add_group(
            f"{supplier['gid']}@supplier",
            supplier["name"] or "Supplier",
            [supplier_role["object_id"]],
            gid=supplier["gid"],
            allow_existing=True,
        )

        if supplier["gid"] in admin_suppliers:
            rbac.add_membership(supplier["gid"], "admin@internal")

    db.commit()
    return True


@migration()
def create_tagged_ed_20260622_001(db: TypeDAL) -> bool:
    """Create and initialize the `tagged_ed` source table and model view."""
    with TaggedModelWithPrio_V1(db):
        db.executesql("""
                      CREATE TABLE tagged_ed (
                                                 id            serial PRIMARY KEY,
                                                 gid           uuid        NOT NULL DEFAULT uuidv4(),
                                                 subject_gid   uuid        NOT NULL,
                                                 predicate     varchar(64) NOT NULL,
                                                 object_gid    uuid        NOT NULL,
                                                 comment       text,
                                                 created_at    timestamp            DEFAULT CURRENT_TIMESTAMP,
                                                 updated_at    timestamp            DEFAULT CURRENT_TIMESTAMP,
                                                 effdt         timestamp            DEFAULT utcnow(),
                                                 effstatus     boolean              DEFAULT TRUE,
                                                 prio          integer              DEFAULT 0,
                                                 last_saved_by varchar,
                                                 sync_gid      uuid                 DEFAULT uuidv7() NOT NULL
                                                     CONSTRAINT tagged_ed_unique_sync_gid UNIQUE
                                             );

                      CREATE INDEX tagged_ed_id_effdt
                          ON tagged_ed (gid ASC, effdt DESC, id ASC);

                      CREATE INDEX idx_tagged_ed_effdt_lookup
                          ON tagged_ed (effdt DESC, gid ASC, prio DESC, effdt DESC) INCLUDE (id);
                      """)

    db.commit()
    return True


@migration()
def create_organisation_ed_20260622_001(db: TypeDAL) -> bool:
    """Create and initialize the `organisation_ed` source table and model view."""
    with OrganisationModelWithPrio_V1(db):
        db.executesql("""
                      CREATE TABLE organisation_ed
                      (
                          id                serial PRIMARY KEY,
                          gid               uuid         NOT NULL DEFAULT uuidv4(),
                          name              varchar(255) NOT NULL,
                          short_name        varchar(255),
                          organisation_type varchar(32)  NOT NULL,
                          brin              varchar(8),
                          vestigingscode    varchar(8),
                          email_domains     text                  DEFAULT '||'::text NOT NULL,
                          website           varchar(500),
                          street            text,
                          number            text,
                          postalcode        varchar(20),
                          city              text,
                          created_at        timestamp             DEFAULT CURRENT_TIMESTAMP,
                          updated_at        timestamp             DEFAULT CURRENT_TIMESTAMP,
                          effdt             timestamp             DEFAULT utcnow(),
                          effstatus         boolean               DEFAULT TRUE,
                          prio              integer               DEFAULT 0,
                          last_saved_by     varchar,
                          sync_gid          uuid                  DEFAULT uuidv7() NOT NULL
                              CONSTRAINT organisation_ed_unique_sync_gid UNIQUE
                      );

                      CREATE INDEX organisation_ed_id_effdt
                          ON organisation_ed (gid ASC, effdt DESC, id ASC);

                      CREATE INDEX idx_organisation_ed_effdt_lookup
                          ON organisation_ed (effdt DESC, gid ASC, prio DESC, effdt DESC) INCLUDE (id);
                      """)

    db.commit()
    return True


@migration()
def setup_organisation_rbac_groups_20260622_002(db: TypeDAL) -> bool:
    """Ensure required organisation RBAC roles exist."""
    from edwh_auth_rbac import AuthRbac

    rbac = AuthRbac(db)
    rbac.define_model(allowed_types=["user", "group"], redefine=True, migrate=False)

    users = rbac.add_group("users@internal", "Users", [], allow_existing=True)
    organisation = rbac.add_group("organisation@internal", "Organisaties", [users], allow_existing=True)
    rbac.add_group("board@internal", "Besturen", [organisation["object_id"]], allow_existing=True)
    rbac.add_group("school@internal", "Scholen", [organisation["object_id"]], allow_existing=True)
    rbac.add_group("location@internal", "Vestigingen", [organisation["object_id"]], allow_existing=True)

    db.commit()
    return True


@migration()
def seed_organisation_data_from_old_server_json_20260622_003(db: TypeDAL) -> bool:
    """Load optional organisation seed rows and relations from JSON endpoints."""
    # including test since it has a custom seed base (json)

    base_url = os.getenv("MIGRATE_SEED_BASE_URL", "")
    if not base_url:
        print("[migrate] missing MIGRATE_SEED_BASE_URL; skipping organisation seed migration")
        return True

    with requests.Session() as session:
        with no_triggers(db):
            import_seed_table_v1(db, base_url=base_url, table_name="organisation_ed", session=session)

        rebuild_all_materialized_tables_v1(db, extra=["recursive_tables"])

        with no_triggers(db):
            backfill_organisation_rbac_identities_v1(db)

        rebuild_all_materialized_tables_v1(db, extra=["recursive_tables"])

        with no_triggers(db):
            import_seed_relationships_v1(db, base_url=base_url, session=session)

        rebuild_all_materialized_tables_v1(db, extra=["recursive_tables"])

    db.commit()
    return True


@migration()
def create_importer_run_reporting_tables_20260622_004(db: TypeDAL) -> bool:
    """Create durable importer-run reporting tables."""
    db.executesql(
        """
        CREATE TABLE importer_run
        (
            id              serial PRIMARY KEY,
            gid             uuid        NOT NULL DEFAULT uuidv4(),
            source          varchar(80) NOT NULL,
            endpoint_type   varchar(40),
            supplier_gid    uuid,
            supplier_name   varchar(255),
            job_key         varchar(255),
            started_at      timestamp   NOT NULL,
            finished_at     timestamp   NOT NULL,
            duration_ms     integer     NOT NULL DEFAULT 0,
            success         boolean     NOT NULL DEFAULT TRUE,
            failure_message text,
            payload_json    json        NOT NULL DEFAULT '{}'::json,
            created_at      timestamp   NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      timestamp   NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE UNIQUE INDEX importer_run_gid_unique
            ON importer_run (gid);
        CREATE UNIQUE INDEX importer_run_job_key_unique
            ON importer_run (job_key) WHERE job_key IS NOT NULL;
        CREATE INDEX idx_importer_run_source_started_at
            ON importer_run (source, started_at DESC);
        CREATE INDEX idx_importer_run_supplier_started_at
            ON importer_run (supplier_gid, started_at DESC);

        CREATE TABLE importer_run_count_stat
        (
            id            serial PRIMARY KEY,
            gid           uuid         NOT NULL DEFAULT uuidv4(),
            run_gid       uuid         NOT NULL REFERENCES importer_run (gid) ON DELETE CASCADE,
            supplier_gid  uuid,
            supplier_name varchar(255),
            count_type    varchar(40)  NOT NULL,
            count_key     varchar(255) NOT NULL,
            count_label   varchar(255),
            metric        varchar(40)  NOT NULL,
            value         integer      NOT NULL DEFAULT 0,
            created_at    timestamp    NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at    timestamp    NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE UNIQUE INDEX importer_run_count_stat_gid_unique
            ON importer_run_count_stat (gid);
        CREATE INDEX idx_importer_run_count_stat_run_gid
            ON importer_run_count_stat (run_gid);
        CREATE INDEX idx_importer_run_count_stat_lookup
            ON importer_run_count_stat (supplier_gid, count_type, metric);

        CREATE TABLE importer_run_error_stat
        (
            id                serial PRIMARY KEY,
            gid               uuid        NOT NULL DEFAULT uuidv4(),
            run_gid           uuid        NOT NULL REFERENCES importer_run (gid) ON DELETE CASCADE,
            supplier_gid      uuid,
            supplier_name     varchar(255),
            entity_type       varchar(20) NOT NULL,
            entity_gid        uuid,
            entity_olid       varchar(255),
            entity_name       varchar(255),
            method_gid        uuid,
            method_name       varchar(255),
            error_code        varchar(80) NOT NULL,
            validation_failed boolean     NOT NULL DEFAULT FALSE,
            created_at        timestamp   NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at        timestamp   NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE UNIQUE INDEX importer_run_error_stat_gid_unique
            ON importer_run_error_stat (gid);
        CREATE INDEX idx_importer_run_error_stat_run_gid
            ON importer_run_error_stat (run_gid);
        CREATE INDEX idx_importer_run_error_stat_supplier_error
            ON importer_run_error_stat (supplier_gid, error_code);
        CREATE INDEX idx_importer_run_error_stat_entity
            ON importer_run_error_stat (entity_type, entity_gid);
        """
    )
    db.commit()
    return True


@migration()
def backfill_organisation_rbac_permissions_20260623_001(db: TypeDAL) -> bool:
    """Backfill explicit organisation permissions from seeded hierarchy relations."""
    backfill_organisation_rbac_permissions_v1(db)
    db.commit()
    return True


@migration()
def convert_supplier_email_domain_to_email_domains_20260623_002(db: TypeDAL) -> bool:
    """Replace the single supplier email domain field with a list:string field."""
    with SupplierModelWithPrio_V1(db):
        db.executesql("""
                      ALTER TABLE supplier_ed
                          ADD COLUMN email_domains text DEFAULT '||'::text NOT NULL;

                      UPDATE supplier_ed
                      SET email_domains = CONCAT('|', LOWER(email_domain), '|')
                          WHERE email_domain IS NOT NULL
                            AND email_domain <> '';

                      ALTER TABLE supplier_ed
                          DROP COLUMN email_domain;
                      """)
    db.commit()
    return True


@migration(requires=add_applog_statistics_tables_20260601_001)
def create_superset_readonly_user_20260622_001(db: TypeDAL) -> bool:
    """Create a read-only PostgreSQL user for Superset."""
    user = os.environ.get("SUPERSET_DB_USER", "superset_readonly")
    password = os.environ["SUPERSET_DB_PASSWORD"]

    if not user.isidentifier() or not user.islower():
        raise ValueError(f"Invalid SUPERSET_DB_USER: {user!r}")

    # user can already exist if running in a test-environment
    # (which only removes tables, instead of a full database wipe)
    role_exists = db.executesql(
        "SELECT 1 FROM pg_roles WHERE rolname = %(user)s",
        placeholders={"user": user},
    )
    if not role_exists:
        db.executesql(
            f"""
            CREATE ROLE {user}
                WITH LOGIN
                NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
            """,  # no S608: all identifiers are in our control)
        )

    db.executesql(
        f"""
        ALTER ROLE {user}
            WITH LOGIN PASSWORD '{password}'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

        GRANT CONNECT ON DATABASE backend TO {user};
        GRANT USAGE ON SCHEMA public TO {user};
        GRANT SELECT ON ALL TABLES IN SCHEMA public TO {user};
        GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO {user};

        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT SELECT ON TABLES TO {user};

        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT SELECT ON SEQUENCES TO {user};
        """,  # no S608: all parameters are in our control so no SQL injection possible)
    )

    db.commit()
    return True


@migration()
def create_dynamic_filter_table_20260630_001(db: TypeDAL) -> bool:
    """Create persisted metadata for public product/method filters."""
    db.executesql("""
                  CREATE TABLE dynamic_filter (
                                                  id          serial PRIMARY KEY,
                                                  gid         uuid         NOT NULL DEFAULT uuidv4() UNIQUE,
                                                  slug        varchar(40)  NOT NULL UNIQUE,
                                                  label       varchar(100) NOT NULL,
                                                  filter_kind varchar(20)  NOT NULL DEFAULT 'dynamic',
                                                  field_name  varchar(100),
                                                  match_mode  varchar(10)  NOT NULL DEFAULT 'contains',
                                                  applies_to  varchar(10)  NOT NULL DEFAULT 'both',
                                                  handler_key varchar(50),
                                                  widget_kind varchar(20),
                                                  is_active   boolean      NOT NULL DEFAULT TRUE,
                                                  sort_order  integer      NOT NULL DEFAULT 0
                                              );
                  """)
    db.commit()
    return True


@migration(requires=create_dynamic_filter_table_20260630_001)
def seed_public_dynamic_filters_20260630_002(db: TypeDAL) -> bool:
    """Seed the public filter configuration to mirror the old platform."""
    if state_of_development == "TEST" and not seed_catalog_configuration:
        # test controls its own data
        return True

    rows = [
        {
            "slug": "q",
            "label": "Zoekterm",
            "filter_kind": "search",
            "field_name": None,
            "match_mode": "contains",
            "applies_to": "both",
            "handler_key": None,
            "widget_kind": "search",
            "sort_order": 0,
        },
        {
            "slug": "cmp",
            "label": "Type",
            "filter_kind": "custom",
            "field_name": "composition",
            "match_mode": "belongs",
            "applies_to": "product",
            "handler_key": "product_composition",
            "widget_kind": "select",
            "sort_order": 10,
        },
        {
            "slug": "vk",
            "label": "Vak",
            "filter_kind": "dynamic",
            "field_name": "subjects",
            "match_mode": "contains",
            "applies_to": "both",
            "handler_key": None,
            "widget_kind": "select",
            "sort_order": 20,
        },
        {
            "slug": "nv",
            "label": "Niveau",
            "filter_kind": "dynamic",
            "field_name": "levels",
            "match_mode": "contains",
            "applies_to": "both",
            "handler_key": None,
            "widget_kind": "select",
            "sort_order": 30,
        },
        {
            "slug": "bschkbr",
            "label": "Beschikbaar",
            "filter_kind": "dynamic",
            "field_name": "available",
            "match_mode": "belongs",
            "applies_to": "both",
            "handler_key": None,
            "widget_kind": "select",
            "sort_order": 40,
        },
        {
            "slug": "bouw",
            "label": "Bouw",
            "filter_kind": "dynamic",
            "field_name": "bouw",
            "match_mode": "contains",
            "applies_to": "product",
            "handler_key": None,
            "widget_kind": "select",
            "sort_order": 50,
        },
        {
            "slug": "tto",
            "label": "TTO",
            "filter_kind": "custom",
            "field_name": "tto",
            "match_mode": "belongs",
            "applies_to": "both",
            "handler_key": "boolean_choice",
            "widget_kind": "select",
            "sort_order": 60,
        },
        {
            "slug": "bdgt",
            "label": "Adviesprijs",
            "filter_kind": "custom",
            "field_name": "recommended_price",
            "match_mode": "belongs",
            "applies_to": "product",
            "handler_key": "budget_range",
            "widget_kind": "select",
            "sort_order": 70,
        },
        {
            "slug": "mdm",
            "label": "Medium",
            "filter_kind": "dynamic",
            "field_name": "physical_digital_mix",
            "match_mode": "belongs",
            "applies_to": "both",
            "handler_key": None,
            "widget_kind": "select",
            "sort_order": 80,
        },
        {
            "slug": "dvcs",
            "label": "Apparaten",
            "filter_kind": "dynamic",
            "field_name": "devices",
            "match_mode": "contains",
            "applies_to": "both",
            "handler_key": None,
            "widget_kind": "select",
            "sort_order": 90,
        },
        {
            "slug": "oses",
            "label": "Besturingssystemen",
            "filter_kind": "dynamic",
            "field_name": "operating_systems",
            "match_mode": "contains",
            "applies_to": "both",
            "handler_key": None,
            "widget_kind": "select",
            "sort_order": 100,
        },
        {
            "slug": "pbsh",
            "label": "Aanbieders",
            "filter_kind": "custom",
            "field_name": "supplier_gid",
            "match_mode": "belongs",
            "applies_to": "both",
            "handler_key": "supplier_lookup",
            "widget_kind": "select",
            "sort_order": 110,
        },
        {
            "slug": "mthd",
            "label": "Methodes",
            "filter_kind": "custom",
            "field_name": "method_gid",
            "match_mode": "belongs",
            "applies_to": "product",
            "handler_key": "method_lookup",
            "widget_kind": "select",
            "sort_order": 120,
        },
    ]

    for row in rows:
        db.executesql(
            """
            INSERT INTO dynamic_filter (
                slug, label, filter_kind, field_name, match_mode, applies_to, handler_key, widget_kind, is_active
            , sort_order)
                VALUES (
                           %(slug)s, %(label)s, %(filter_kind)s, %(field_name)s, %(match_mode)s, %(applies_to)s
                       , %(handler_key)s, %(widget_kind)s, TRUE, %(sort_order)s)
            """,
            placeholders=row,
        )

    db.commit()
    return True


@migration()
def create_dynamic_sort_table_20260702_001(db: TypeDAL) -> bool:
    """Create persisted metadata for public product/method sort options."""
    db.executesql("""
                  CREATE TABLE dynamic_sort (
                                                id               serial PRIMARY KEY,
                                                gid              uuid         NOT NULL DEFAULT uuidv4() UNIQUE,
                                                slug             varchar(40)  NOT NULL UNIQUE,
                                                label            varchar(100) NOT NULL,
                                                applies_to       varchar(10)  NOT NULL DEFAULT 'both',
                                                order_expression varchar(255) NOT NULL,
                                                is_default       boolean      NOT NULL DEFAULT FALSE,
                                                is_active        boolean      NOT NULL DEFAULT TRUE,
                                                sort_order       integer      NOT NULL DEFAULT 0
                                            );
                  """)
    db.commit()
    return True


@migration(requires=create_dynamic_sort_table_20260702_001)
def seed_public_dynamic_sorts_20260702_002(db: TypeDAL) -> bool:
    """Seed the public sort configuration for catalogue pages."""
    if state_of_development == "TEST" and not seed_catalog_configuration:
        # test controls its own data
        return True

    db.executesql(
        """
        INSERT INTO dynamic_sort (
            slug, label, applies_to, order_expression, is_default, is_active, sort_order)
            VALUES ('name_asc', 'Alfabetisch (A-Z)', 'both', 'name, id', TRUE, TRUE, 0)
                 , ('name_desc', 'Alfabetisch (Z-A)', 'both', '~name, ~id', FALSE, TRUE, 10)
                 , ('publication_year_asc', 'Publicatiejaar (oud-nieuw)', 'both', 'publication_date, name, id', FALSE
            , TRUE, 20)
                 , ('publication_year_desc', 'Publicatiejaar (nieuw-oud)', 'both', '~publication_date, ~name, ~id'
            , FALSE, TRUE, 30)
                 , ('random', 'Willekeurig', 'both', 'random', FALSE, TRUE, 40);
        """
    )
    db.commit()
    return True


@migration()
def add_supplier_endpoint_publisher_20260707_001(db: TypeDAL) -> bool:
    """Add the optional Edu-V publisher selector for shared Kennisnet endpoints."""
    with SupplierModelWithPrio_V1(db):
        db.executesql("""
                      ALTER TABLE supplier_ed
                          ADD COLUMN endpoint_publisher varchar(255);
                      """)
    db.commit()
    return True


@migration(requires=add_supplier_endpoint_publisher_20260707_001)
def add_publication_date_to_product_and_method_20260709_001(db: TypeDAL) -> bool:
    """Add `publication_date` to catalog tables and repoint publication-year sorts."""
    with ProductModelWithPrio_V1(db):
        db.executesql("""
                      ALTER TABLE product_ed
                          ADD COLUMN IF NOT EXISTS publication_date date;
                      """)

    with MethodModelWithPrio_V1(db):
        db.executesql("""
                      ALTER TABLE method_ed
                          ADD COLUMN IF NOT EXISTS publication_date date;
                      """)

    db.executesql("""
                  UPDATE dynamic_sort
                  SET order_expression = 'publication_date, name, id'
                      WHERE slug = 'publication_year_asc';
                  """)
    db.executesql("""
                  UPDATE dynamic_sort
                  SET order_expression = '~publication_date, ~name, ~id'
                      WHERE slug = 'publication_year_desc';
                  """)

    db.commit()
    return True


@migration(requires=add_publication_date_to_product_and_method_20260709_001)
def add_eduv_product_fields_and_import_run_warnings_20260709_002(db: TypeDAL) -> bool:
    """Add Edu-V product fields and importer-run warning storage."""
    with ProductModelWithPrio_V1(db):
        db.executesql("""
                      ALTER TABLE product_ed
                          ADD COLUMN payment_models            text,
                          ADD COLUMN product_usages            text,
                          ADD COLUMN related_products          text,
                          ADD COLUMN specific_access_urls      text,
                          ADD COLUMN specific_access_url_types text,
                          ADD COLUMN copyright_type            varchar(255),
                          ADD COLUMN deprecation_date          date,
                          ADD COLUMN end_of_life_date          date,
                          ADD COLUMN follow_up_product         uuid,
                          ADD COLUMN for_sale                  boolean,
                          ADD COLUMN intended_end_user_role    varchar(255),
                          ADD COLUMN is_consumption_product    boolean,
                          ADD COLUMN sale_unit_size            integer,
                          ADD COLUMN supported_until_date      date;
                      """)

    db.executesql("""
                  ALTER TABLE importer_run
                      ADD COLUMN warnings_json json NOT NULL DEFAULT '[]'::json;
                  """)

    db.commit()
    return True


@migration(requires=add_eduv_product_fields_and_import_run_warnings_20260709_002)
def add_error_details_to_importer_run_error_stat_20260709_003(db: TypeDAL) -> bool:
    """Add generic JSON details to persisted importer run errors."""
    db.executesql("""
                  ALTER TABLE importer_run_error_stat
                      ADD COLUMN error_details json;
                  """)

    db.commit()
    return True


@migration()
def create_locations_without_organisation_mapping_report_20260713_001(db: TypeDAL) -> bool:
    """Create the live Superset report for locations without school mappings."""
    with LocationsWithoutOrganisationMappingReport_V1(db):
        pass
    db.commit()
    return True


@migration()
def create_locations_without_brin_vest_code_report_20260713_002(db: TypeDAL) -> bool:
    """Create the live Superset report for locations without BRIN-location codes."""
    with LocationsWithoutBrinVestCodeReport_V1(db):
        "ensure the report exists"

    db.commit()
    return True


@migration()
def create_schools_without_homepage_url_report_20260713_003(db: TypeDAL) -> bool:
    """Create the live Superset report for schools without homepage URLs."""
    with SchoolsWithoutHomepageUrlReport_V1(db):
        "ensure the report exists"

    db.commit()
    return True


@migration()
def create_schools_without_email_domain_report_20260713_004(db: TypeDAL) -> bool:
    """Create the live Superset report for schools without email domains."""
    with SchoolsWithoutEmailDomainReport_V1(db):
        "ensure the report exists"

    db.commit()
    return True


@migration()
def create_catalog_search_report_20260713_005(db: TypeDAL) -> bool:
    """Create the materialized report for catalog search activity."""
    with CatalogSearchReport_V1(db):
        "ensure the report exists"

    db.commit()
    return True


@migration(requires=create_catalog_search_report_20260713_005)
def convert_catalog_search_report_active_filters_to_jsonb_20260716_001(db: TypeDAL) -> bool:
    """Rebuild the catalog search report with JSONB active filters."""
    with CatalogSearchReport_V1b(db):
        "ensure the updated report exists"

    db.commit()
    return True


@migration(requires=convert_catalog_search_report_active_filters_to_jsonb_20260716_001)
def add_vestigingscode_to_school_data_quality_reports_20260716_002(db: TypeDAL) -> bool:
    """Rebuild school data-quality reports with vestigingscode columns."""
    with SchoolsWithoutHomepageUrlReport_V1b(db), SchoolsWithoutEmailDomainReport_V1b(db):
        "ensure the updated reports exist"

    db.commit()
    return True


@migration()
def create_static_content_table_20260720_001(db: TypeDAL) -> bool:
    """Create storage for admin-editable public-page content sections."""
    db.executesql("""
                  CREATE TABLE static_content (
                                                  id      serial PRIMARY KEY,
                                                  gid     uuid         NOT NULL DEFAULT uuidv4() UNIQUE,
                                                  scope   varchar(120) NOT NULL,
                                                  section varchar(120) NOT NULL,
                                                  content text         NOT NULL,
                                                  CONSTRAINT static_content_scope_section_unique UNIQUE (scope, section)
                                              );
                  """)
    db.commit()
    return True


@migration(requires=convert_catalog_search_report_active_filters_to_jsonb_20260716_001)
def add_catalog_search_result_scores_20260721_002(db: TypeDAL) -> bool:
    """Rebuild the catalog-search report with displayed relevance scores."""
    with CatalogSearchReport_V1c(db):
        "ensure the updated report exists"

    db.commit()
    return True


@migration()
def create_search_rank_weight_table_20260721_003(db: TypeDAL) -> bool:
    """Create editable weights for product and method search ranking."""
    db.executesql("""
                  CREATE TABLE search_rank_weight
                  (
                      id            serial PRIMARY KEY,
                      gid           uuid         NOT NULL DEFAULT uuidv4() UNIQUE,
                      entity_kind   varchar(10)  NOT NULL,
                      key           varchar(40)  NOT NULL,
                      section       varchar(20)  NOT NULL,
                      sort_order    integer      NOT NULL DEFAULT 0,
                      label         varchar(100) NOT NULL,
                      source_field  varchar(100) NOT NULL,
                      foreign_key   varchar(100),
                      related_table varchar(100),
                      related_key   varchar(100),
                      exact         integer,
                      prefix        integer,
                      contains      integer,
                      trigram       integer,
                      CONSTRAINT search_rank_weight_entity_key_unique UNIQUE (entity_kind, key)
                  );
                  """)
    db.executesql(
        """
        INSERT INTO search_rank_weight ( entity_kind, key, section, sort_order, label, source_field, foreign_key
                                       , related_table, related_key, exact
                                       , prefix, contains, trigram)
        VALUES ('product', 'name', 'name', 10, 'Productnaam', 'name', NULL, NULL, NULL, 1200, 500, 300, 350)
             , ( 'product', 'related_method_name', 'related', 20, 'Methodenaam', 'name', 'method_gid', 'Method'
               , 'gid', 60, NULL, 45, NULL)
             , ( 'product', 'supplier_name', 'related', 10, 'Leveranciersnaam', 'name', 'supplier_gid', 'Supplier'
               , 'gid', 70, NULL, 50, NULL)
             , ('product', 'olid', 'identifier', 10, 'Product-OLID', 'olid', NULL, NULL, NULL, 90, NULL, 80, NULL)
             , ('method', 'name', 'name', 10, 'Methodenaam', 'name', NULL, NULL, NULL, 1200, 500, 300, 350)
             , ( 'method', 'related_product_name', 'related', 20, 'Productnaam', 'name', 'gid', 'Product'
               , 'method_gid', 60, NULL, 45, NULL)
             , ( 'method', 'supplier_name', 'related', 10, 'Leveranciersnaam', 'name', 'supplier_gid', 'Supplier'
               , 'gid', 70, NULL, 50, NULL)
             , ('method', 'olid', 'identifier', 10, 'Methode-OLID', 'olid', NULL, NULL, NULL, 90, NULL, 80, NULL);
        """,
    )
    db.commit()
    return True


@migration()
def create_decision_process_tables_20260803_001(db: TypeDAL) -> bool:
    """Create the empty guided decision-process schema."""
    db.executesql(
        """
        CREATE TABLE decision_team (
                                       id           serial PRIMARY KEY,
                                       gid          uuid         NOT NULL DEFAULT uuidv4() UNIQUE,
                                       location_gid uuid         NOT NULL,
                                       name         varchar(255) NOT NULL,
                                       courses      text         NOT NULL DEFAULT '||',
                                       levels       text         NOT NULL DEFAULT '||',
                                       years        text         NOT NULL DEFAULT '||',
                                       active       boolean      NOT NULL DEFAULT TRUE,
                                       created_at   timestamp             DEFAULT CURRENT_TIMESTAMP,
                                       updated_at   timestamp             DEFAULT CURRENT_TIMESTAMP
                                   );

        CREATE TABLE decision_process (
                                          id                 serial PRIMARY KEY,
                                          gid                uuid        NOT NULL DEFAULT uuidv4() UNIQUE,
                                          team_gid           uuid        NOT NULL REFERENCES decision_team (gid),
                                          schoolyear         varchar(20) NOT NULL,
                                          start_date         date        NOT NULL,
                                          active             boolean     NOT NULL DEFAULT TRUE,
                                          process_stage      varchar(10) NOT NULL DEFAULT 'team',
                                          courses            text        NOT NULL DEFAULT '||',
                                          levels             text        NOT NULL DEFAULT '||',
                                          years              text        NOT NULL DEFAULT '||',
                                          vision             text        NOT NULL DEFAULT '',
                                          project_leader_gid uuid,
                                          reporter_gid       uuid,
                                          team_planning      text        NOT NULL DEFAULT '',
                                          ai_usage           integer     NOT NULL DEFAULT 0,
                                          created_at         timestamp            DEFAULT CURRENT_TIMESTAMP,
                                          updated_at         timestamp            DEFAULT CURRENT_TIMESTAMP
                                      );

        CREATE TABLE decision_process_note (
                                               id               serial PRIMARY KEY,
                                               gid              uuid         NOT NULL DEFAULT uuidv4() UNIQUE,
                                               organisation_gid uuid         NOT NULL,
                                               theme            varchar(120) NOT NULL,
                                               content          text         NOT NULL DEFAULT '',
                                               created_at       timestamp             DEFAULT CURRENT_TIMESTAMP,
                                               updated_at       timestamp             DEFAULT CURRENT_TIMESTAMP
                                           );

        CREATE TABLE decision_material_selection (
                                                     id            serial PRIMARY KEY,
                                                     gid           uuid         NOT NULL DEFAULT uuidv4() UNIQUE,
                                                     process_gid   uuid         NOT NULL REFERENCES decision_process (gid),
                                                     name          varchar(255) NOT NULL,
                                                     olid          varchar(255),
                                                     material_type varchar(10)  NOT NULL DEFAULT 'bought',
                                                     created_at    timestamp             DEFAULT CURRENT_TIMESTAMP,
                                                     updated_at    timestamp             DEFAULT CURRENT_TIMESTAMP
                                                 );

        CREATE TABLE decision_pros_and_cons (
                                                id                     serial PRIMARY KEY,
                                                gid                    uuid       NOT NULL DEFAULT uuidv4() UNIQUE,
                                                process_gid            uuid       NOT NULL REFERENCES decision_process (gid),
                                                user_gid               uuid       NOT NULL,
                                                material_selection_gid uuid,
                                                item_type              varchar(3) NOT NULL,
                                                theme                  varchar(120),
                                                content                text       NOT NULL DEFAULT '',
                                                sort_order             integer    NOT NULL DEFAULT 0,
                                                created_at             timestamp           DEFAULT CURRENT_TIMESTAMP,
                                                updated_at             timestamp           DEFAULT CURRENT_TIMESTAMP
                                            );

        CREATE TABLE decision_theme_vision (
                                               id          serial PRIMARY KEY,
                                               gid         uuid         NOT NULL DEFAULT uuidv4() UNIQUE,
                                               process_gid uuid         NOT NULL REFERENCES decision_process (gid),
                                               theme       varchar(120) NOT NULL,
                                               summary     text         NOT NULL DEFAULT '',
                                               sort_order  integer      NOT NULL DEFAULT 0,
                                               created_at  timestamp             DEFAULT CURRENT_TIMESTAMP,
                                               updated_at  timestamp             DEFAULT CURRENT_TIMESTAMP
                                           );

        CREATE INDEX decision_team_location_gid_index
            ON decision_team (location_gid);

        CREATE INDEX decision_process_team_gid_index
            ON decision_process (team_gid);

        CREATE INDEX decision_process_active_index
            ON decision_process (active, updated_at DESC);

        CREATE INDEX decision_material_selection_process_gid_index
            ON decision_material_selection (process_gid);

        CREATE INDEX decision_pros_and_cons_process_gid_index
            ON decision_pros_and_cons (process_gid);

        CREATE INDEX decision_theme_vision_process_gid_index
            ON decision_theme_vision (process_gid);
        """,  # noqa: E501
    )
    db.commit()
    return True


@migration()
def create_learning_material_view_20260803_002(db: TypeDAL) -> bool:
    """Create the materialized catalog relation used by the material picker."""
    with LearningMaterial_V1(db):
        "ensure the catalog view exists"

    db.commit()
    return True


@migration(requires=add_vestigingscode_to_school_data_quality_reports_20260716_002)
def index_email_domain_for_invite_lookup_20260807_001(db: TypeDAL) -> bool:
    """Index the email domain so invite similarity lookup stops scanning whole tables."""
    domain_expression = email_domain_sql_v1("email")

    db.executesql(f"""
    CREATE INDEX auth_user_email_domain_idx
        ON auth_user ({domain_expression});
    """)

    db.executesql(f"""
    CREATE INDEX identity_email_domain_idx
        ON identity ({domain_expression})
     WHERE object_type = 'user';
    """)

    db.commit()
    return True


@migration()
def index_global_search_text_20260818_001(db: TypeDAL) -> bool:
    """Rebuild searchable models with their trigram indexes."""
    # one-by-one so it doesn't confuse the derived views:

    with ProductModelWithPrio_V1(db):
        "running the context manager ensures the new indexes are (re)added."

    with MethodModelWithPrio_V1(db):
        "running the context manager ensures the new indexes are (re)added."

    with SupplierModelWithPrio_V1(db):
        "running the context manager ensures the new indexes are (re)added."

    db.commit()
    return True


@migration()
def create_effective_dated_decision_teams_20260818_002(db: TypeDAL) -> bool:
    """Convert teaching teams to an effective-dated source and current model."""
    # This must happen before conversion: the foreign key depends on the source
    # table's unique gid constraint, which `convert_to_effdt_v1` removes. Do not
    # move it into the model manager, which runs only after the source conversion.
    db.executesql("""
                  ALTER TABLE decision_process
                      DROP CONSTRAINT IF EXISTS decision_process_team_gid_fkey;
                  """)
    convert_to_effdt_v1(db, "decision_team")
    with DecisionTeamModelWithPrio_V1(db):
        "create the current decision-team model"
    db.commit()
    return True


@migration()
def create_effective_dated_decision_process_notes_20260818_003(db: TypeDAL) -> bool:
    """Convert organisation guidance notes to an effective-dated source and current model."""
    convert_to_effdt_v1(db, "decision_process_note")
    with DecisionProcessNoteModelWithPrio_V1(db):
        "create the current decision-process-note model"
    db.commit()
    return True


@migration()
def align_organisation_rbac_permissions_20260824_001(db: TypeDAL) -> bool:
    """Make boards read-only for the schools and locations below them."""
    backfill_organisation_rbac_permissions_v2(db)
    db.commit()
    return True


def _replace_theme_key_column(
    db: TypeDAL,
    table: str,
    column: str,
    theme_gid_lookup: dict[str, str],
) -> None:
    """Replace legacy theme keys with their seeded definition GIDs."""
    db.executesql(f"ALTER TABLE {table} ADD COLUMN {column}_gid uuid;")
    for legacy_key, gid in theme_gid_lookup.items():
        db.executesql(
            f"""
                UPDATE {table} SET {column}_gid = %(gid)s WHERE {column} = %(legacy_key)s;
                """,  # noqa: S608 - variables are constrained to literal identifiers at the call sites
            placeholders={"gid": gid, "legacy_key": legacy_key},
        )
    unknown = db.executesql(
        f"""
        SELECT DISTINCT {column}
          FROM {table}
         WHERE {column} IS NOT NULL
           AND {column}_gid IS NULL;
    """,  # noqa: S608 - variables are constrained to literal identifiers at the call sites
    )
    if unknown:
        db.executesql(
            f"DELETE FROM {table} WHERE {column}_gid IS NULL;"  # noqa: S608 - see explanation above
        )

    db.executesql(f"ALTER TABLE {table} DROP COLUMN {column};")
    db.executesql(f"ALTER TABLE {table} RENAME COLUMN {column}_gid TO {column};")


@migration(requires=align_organisation_rbac_permissions_20260824_001)
def create_vision_theme_definitions_20260824_002(db: TypeDAL) -> bool:
    """Move the fixed vision-theme catalogue into effective-dated storage."""
    definitions = (
        {
            "gid": "6a529aa6-3e8d-4609-9ce2-abdfbfc98685",
            "legacy_key": "opbouw-leerdoelen",
            "title": "Opbouw en leerdoelen",
            "info_url": "https://onzeleermiddelen.nl/opbouw-en-leerdoelen/",
            "description": "De structuur van een leermiddel (hoofdstukken, paragrafen, lesvolgorde) "
            "en de expliciete, taal- en positioneringswijze van leerdoelen bepalen inzicht, "
            "vakintegratie en de selectie ervan.",
        },
        {
            "gid": "09d87008-4862-414e-9016-9986bfe04b11",
            "legacy_key": "diversiteit-differentieren",
            "title": "Diversiteit en differentieren",
            "info_url": "https://onzeleermiddelen.nl/diversiteit-en-differentieren/",
            "description": "Bij het kiezen van leermiddelen moet men de differentiatie- en arrangemogelijkheden "
            "beoordelen, flexibele versus vaste methodes vergelijken, "
            "en waar nodig open materiaal integreren voor alle niveaus.",
        },
        {
            "gid": "5712888d-33a8-4d90-a357-6149506fa563",
            "legacy_key": "kwaliteit-effectiviteit",
            "title": "Kwaliteit en effectiviteit",
            "info_url": "https://onzeleermiddelen.nl/kwaliteit-en-effectiviteit/",
            "description": "Hoogwaardige, effectieve leermiddelen, gebaseerd op actuele wetenschap, "
            "moeten aansluiten bij schoolvisie en didactiek, om leerprocessen, motivatie "
            "en brede ontwikkeling doelgericht te ondersteunen.",
        },
        {
            "gid": "789579d9-9ce0-48c8-8cf5-07a73dac5f6b",
            "legacy_key": "evalueren-toetsen",
            "title": "Evalueren en toetsen",
            "info_url": "https://onzeleermiddelen.nl/evalueren-en-toetsen/",
            "description": "Evaluatie- en toetsopties van leermiddelen varieren in vorm, moment en ondersteuning, "
            "bieden formatieve en summatieve, inclusieve keuzes "
            "(schriftelijk, mondeling, creatief, digitaal) afgestemd op leerling- en docentbehoeften.",
        },
        {
            "gid": "734cafe7-af9a-4858-9b25-22a254f89004",
            "legacy_key": "vormgeving-toegankelijkheid",
            "title": "Vormgeving en toegankelijkheid",
            "info_url": "https://onzeleermiddelen.nl/vormgeving-en-toegankelijkheid/",
            "description": "Vormgeving en toegankelijkheid van leermiddelen bepalen hun kwaliteit en geschiktheid "
            "voor diverse doelgroepen, waarbij ontwerp, contrast, lettergrootte "
            "en ondersteunende technologie essentieel zijn.",
        },
        {
            "gid": "66ddb7a4-d1b5-4c73-9631-df998efdbfdd",
            "legacy_key": "belevingswereld-leefomgeving",
            "title": "Belevingswereld en (leef)omgeving",
            "info_url": "https://onzeleermiddelen.nl/belevingswereld-en-leefomgeving/",
            "description": "Leermateriaal moet aansluiten op zowel de belevingswereld als "
            "de leefomgeving van leerlingen: hun ervaringen, waarden, cultuur, identiteit "
            "en voorkennis, met passende representatie en herkenbare contexten, eventueel aangevuld.",
        },
        {
            "gid": "f82091da-7f2c-44e0-9a7b-fde71b9bde75",
            "legacy_key": "aanpasbaarheid-actualiteit",
            "title": "Aanpasbaarheid en actualiteit",
            "info_url": "https://onzeleermiddelen.nl/aanpasbaarheid-en-actualiteit/",
            "description": "De aanpasbaarheid en actualiteit van leermiddelen bepalen hun flexibiliteit, "
            "zodat onderwijs sneller inspeelt op context, wensen, nieuwe ontwikkelingen "
            "en veranderende doelen, met een passende leraarrol.",
        },
        {
            "gid": "a993d4fa-4721-4141-8536-1885869f7a8c",
            "legacy_key": "materiaalvormen-technologie",
            "title": "Materiaalvormen en technologie",
            "info_url": "https://onzeleermiddelen.nl/materiaalvormen-en-technologie/",
            "description": "Materiaalvormen (boeken, werkbladen, digitaal) en technologie (digitaal lesmateriaal, AI) "
            "varieren per school, vak, doelgroep en leraar; kies passend volgens "
            "effectiviteit voor leerlingondersteuning.",
        },
        {
            "gid": "ad0d5501-f3f4-4a39-a4c6-9116b057e5e9",
            "legacy_key": "co-creatie-doorontwikkeling",
            "title": "Co-creatie en (door)ontwikkeling",
            "info_url": "https://onzeleermiddelen.nl/co-creatie-en-doorontwikkeling/",
            "description": "Co-creatie betekent dat leraren, leerlingen en makers samen leermiddelen ontwikkelen "
            "en doorontwikkelen, waarbij methoden varieren van feedbackknoppen tot focusgroepen, "
            "en de mate hiervan beinvloedt de materiaalkeuze.",
        },
        {
            "gid": "5e35c450-0c3c-4918-a255-5da7455392ff",
            "legacy_key": "onafhankelijkheid-dataveiligheid",
            "title": "Onafhankelijkheid en data-veiligheid",
            "info_url": "https://onzeleermiddelen.nl/onafhankelijkheid-en-data-veiligheid/",
            "description": "Onafhankelijkheid en dataveiligheid bepalen hoe sterk scholen afhankelijk zijn "
            "van leveranciers, waarbij verticale en horizontale integratie keuzemogelijkheden "
            "beperken en privacy, transparantie en controle over persoonsgegevens cruciaal zijn.",
        },
        {
            "gid": "e47e618b-7316-47b3-a23d-caa80a735d21",
            "legacy_key": "transparant-eerlijk",
            "title": "Transparant en eerlijk",
            "info_url": "https://onzeleermiddelen.nl/transparant-en-eerlijk/",
            "description": "Transparantie en eerlijkheid bij leermiddelen betekenen duidelijke kosten- "
            "en ontwikkelingsinformatie, geen verborgen verplichtingen, "
            "en inzicht in herinvestering versus winst, zodat scholen bewuste partners kiezen.",
        },
        {
            "gid": "5063565f-c6c8-4a09-b40f-071a2b627428",
            "legacy_key": "verantwoord-duurzaam",
            "title": "Verantwoord en duurzaam",
            "info_url": "https://onzeleermiddelen.nl/verantwoord-en-duurzaam/",
            "description": "Verantwoord gebruik van leermiddelen vraagt bewuste materiaal- en productkeuzes, "
            "waarbij zowel de duurzame ontwikkeling door makers als het efficiente, afval-beperkende "
            "gebruik door gebruikers wordt meegewogen.",
        },
    )

    with VisionThemeDefinitionModelWithPrio_V1(db):
        db.executesql("""
                      CREATE TABLE vision_theme_definition_ed
                      (
                          id            serial PRIMARY KEY,
                          gid           uuid          NOT NULL,
                          title         varchar(255)  NOT NULL,
                          description   text          NOT NULL,
                          info_url      varchar(2048) NOT NULL,
                          sort_order    integer       NOT NULL DEFAULT 0,
                          effdt         timestamp     NOT NULL DEFAULT utcnow(),
                          effstatus     boolean       NOT NULL DEFAULT TRUE,
                          prio          integer       NOT NULL DEFAULT 0,
                          last_saved_by varchar       NOT NULL DEFAULT 'migration/create_vision_theme_definitions',
                          created_at    timestamp     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                          updated_at    timestamp     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                          sync_gid      uuid          NOT NULL DEFAULT uuidv7()
                              CONSTRAINT vision_theme_definition_ed_unique_sync_gid UNIQUE
                      );

                      CREATE INDEX vision_theme_definition_ed_id_effdt
                          ON vision_theme_definition_ed (gid ASC, effdt DESC, id ASC);
                      """)

    for sort_order, definition in enumerate(definitions):
        db.executesql(
            """
            INSERT INTO vision_theme_definition_ed (gid, title, description, info_url, sort_order)
            VALUES (%(gid)s, %(title)s, %(description)s, %(info_url)s, %(sort_order)s);
            """,
            placeholders=definition | {"sort_order": sort_order},
        )

    theme_gids_by_value = {
        value: row["gid"] for row in definitions for value in (row["legacy_key"], row["title"], row["gid"])
    }

    _replace_theme_key_column(
        db,
        table="vision_ed",
        column="onderwijskwaliteit",
        theme_gid_lookup=theme_gids_by_value,
    )
    _replace_theme_key_column(
        db,
        table="decision_process_note_ed",
        column="theme",
        theme_gid_lookup=theme_gids_by_value,
    )
    _replace_theme_key_column(
        db,
        table="decision_pros_and_cons",
        column="theme",
        theme_gid_lookup=theme_gids_by_value,
    )
    _replace_theme_key_column(
        db,
        table="decision_theme_vision",
        column="theme",
        theme_gid_lookup=theme_gids_by_value,
    )

    with VisionModelWithPrio_V1(db):
        "rebuild the vision model after changing its theme key"

    with DecisionProcessNoteModelWithPrio_V1(db):
        "rebuild the guidance-note model after changing its theme key"

    db.commit()
    return True


@migration(requires=add_catalog_search_result_scores_20260721_002)
def add_catalog_search_session_gid_20260825_001(db: TypeDAL) -> bool:
    """Rebuild the catalog-search report with session and login-state columns."""
    with CatalogSearchReport_V1d(db):
        "ensure the updated report exists"

    db.commit()
    return True


@migration()
def add_supplier_endpoint_pagination_20260828_001(db: TypeDAL) -> bool:
    """Add the optional pagination setting for supplier Edu-V endpoints."""
    with SupplierModelWithPrio_V1(db):
        db.executesql("""
        ALTER TABLE supplier_ed
            ADD COLUMN endpoint_uses_pagination boolean NOT NULL DEFAULT FALSE;
        """)
    db.commit()
    return True


@migration()
def create_effective_dated_dynamic_filters_20260831_001(db: TypeDAL) -> bool:
    """Convert dynamic filter settings to effective-dated storage."""
    convert_to_effdt_v1(db, "dynamic_filter")
    db.executesql("""
    ALTER TABLE dynamic_filter_ed DROP CONSTRAINT dynamic_filter_slug_key;
    ALTER TABLE dynamic_filter_ed
        ADD COLUMN created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
        ADD COLUMN updated_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP;
    """)
    with DynamicFilterModelWithPrio_V1(db):
        "ensure the current model exists"
    db.commit()
    return True


@migration()
def create_effective_dated_dynamic_sorts_20260831_002(db: TypeDAL) -> bool:
    """Convert dynamic sort settings to effective-dated storage."""
    convert_to_effdt_v1(db, "dynamic_sort")
    db.executesql("""
    ALTER TABLE dynamic_sort_ed DROP CONSTRAINT dynamic_sort_slug_key;
    ALTER TABLE dynamic_sort_ed
        ADD COLUMN created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
        ADD COLUMN updated_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP;
    """)
    with DynamicSortModelWithPrio_V1(db):
        "ensure the current model exists"

    db.commit()
    return True


@migration()
def create_effective_dated_search_rank_weights_20260831_003(db: TypeDAL) -> bool:
    """Convert search relevance weights to effective-dated storage."""
    convert_to_effdt_v1(db, "search_rank_weight")
    db.executesql("""
    ALTER TABLE search_rank_weight_ed DROP CONSTRAINT search_rank_weight_entity_key_unique;
    ALTER TABLE search_rank_weight_ed
        ADD COLUMN created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
        ADD COLUMN updated_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP;
    """)
    with SearchRankWeightModelWithPrio_V1(db):
        "ensure the current model exists"
    db.commit()
    return True


@migration()
def create_importer_run_event_20260907_001(db: TypeDAL) -> bool:
    """Create one generic event stream for durable importer-run reporting."""
    db.executesql("""
                  CREATE TABLE importer_run_event (
                      id            serial PRIMARY KEY,
                      gid           uuid        NOT NULL DEFAULT uuidv4(),
                      run_gid       uuid        NOT NULL REFERENCES importer_run (gid) ON DELETE CASCADE,
                      supplier_gid  uuid,
                      supplier_name varchar(255),
                      event_type    varchar(40) NOT NULL,
                      scope_type    varchar(40),
                      scope_key     varchar(255),
                      scope_label   varchar(255),
                      metric        varchar(80) NOT NULL,
                      entity_type   varchar(20) NOT NULL,
                      entity_gid    uuid,
                      entity_olid   varchar(255),
                      entity_name   varchar(255),
                      value         integer,
                      details       json,
                      created_at    timestamp   NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      updated_at    timestamp   NOT NULL DEFAULT CURRENT_TIMESTAMP
                  );
                  CREATE UNIQUE INDEX importer_run_event_gid_unique ON importer_run_event (gid);
                  CREATE INDEX idx_importer_run_event_run_type ON importer_run_event (run_gid, event_type);
                  CREATE INDEX idx_importer_run_event_supplier_metric ON importer_run_event (supplier_gid, metric);
                  """)
    db.commit()
    return True


@migration(requires=create_importer_run_event_20260907_001)
def drop_legacy_importer_run_result_tables_20260908_001(db: TypeDAL) -> bool:
    """Remove result tables superseded by the generic importer-run event stream."""
    db.executesql("""
        DROP TABLE importer_run_count_stat;
        DROP TABLE importer_run_error_stat;
    """)
    # todo: build views to replace these?
    db.commit()
    return True


@migration(requires=drop_legacy_importer_run_result_tables_20260908_001)
def create_importer_run_event_compatibility_views_20260910_001(db: TypeDAL) -> bool:
    """Create legacy reporting views backed by importer-run events."""
    with ImporterRunEventCompatibilityViews_V1(db):
        "ensure the compatibility views exist"

    db.commit()
    return True


@migration(requires=create_importer_run_event_compatibility_views_20260910_001)
def add_importer_run_phase_20260911_001(db: TypeDAL) -> bool:
    """Track importer-run progress separately from its final outcome."""
    db.executesql("""
        ALTER TABLE importer_run
            ADD COLUMN phase varchar(40) NOT NULL DEFAULT 'completed';
        UPDATE importer_run
            SET phase = 'failed'
            WHERE success = FALSE;
        ALTER TABLE importer_run
            ALTER COLUMN finished_at DROP NOT NULL,
            ALTER COLUMN success DROP NOT NULL;
    """)
    db.commit()
    return True


def _canonical_unregistered_olid(olid: str) -> str:
    """Return the slug-based form of a legacy unregistered OLID."""
    marker = "olid://unregistered/"
    if not olid.startswith(marker):
        return olid

    identifier, separator, _ = olid.rpartition("#")
    if not separator:
        return olid

    prefix, separator, key = identifier.removeprefix(marker).partition("/")
    if not separator:
        return olid

    return generate(prefix, key)


def _replace_legacy_unregistered_olids(db: TypeDAL, table: t.LiteralString, column: t.LiteralString) -> None:
    """Replace legacy raw-key OLIDs in one known persisted column."""
    rows = db.executesql(
        f"""
        SELECT DISTINCT {column}
        FROM {table}
        WHERE {column} IS NOT NULL
        ;""",  # noqa S608 - both injected values are Literal Strings
    )
    canonical_values = {str(row[0]): _canonical_unregistered_olid(str(row[0])) for row in rows}

    old_values_by_new: dict[str, list[str]] = {}
    for old, new in canonical_values.items():
        old_values_by_new.setdefault(new, []).append(old)
    collisions = {new: old_values for new, old_values in old_values_by_new.items() if len(old_values) > 1}
    if collisions:
        raise ValueError(f"Cannot migrate colliding {table}.{column} OLIDs: {collisions}")

    replacements = {old: new for old, new in canonical_values.items() if old != new}
    for old, new in replacements.items():
        db.executesql(
            f"""
                  UPDATE {table}
                  SET {column} = %(new)s
                  WHERE {column} = %(old)s
                  ;""",  # noqa S608 - both injected values are Literal Strings
            placeholders={
                "old": old,
                "new": new,
            },
        )


@migration(requires=add_importer_run_phase_20260911_001)
def slugify_unregistered_olids_20260915_002(db: TypeDAL) -> bool:
    """Replace raw fallback keys with their canonical readable slug OLIDs."""
    olid_columns: t.Iterable[tuple[t.LiteralString, t.LiteralString]] = (
        ("supplier_ed", "olid"),
        ("method_ed", "olid"),
        ("product_ed", "olid"),
        ("vision_ed", "olid"),
        ("decision_material_selection", "olid"),
        ("importer_run_event", "entity_olid"),
    )
    effdt_models = set[t.LiteralString]()
    with no_triggers(db):
        for table, column in olid_columns:
            if table.endswith("_ed"):
                effdt_models.add(table.removesuffix("_ed"))

            _replace_legacy_unregistered_olids(db, table, column)

    for model in effdt_models:
        db.executesql(f"SELECT rebuild_{model}_model();")

    db.executesql("REFRESH MATERIALIZED VIEW learning_material;")
    db.commit()
    return True


@migration()
def create_location_product_usage_report_20260917_002(db: TypeDAL) -> bool:
    """Create the live location product-usage report from decision processes."""
    with LocationProductUsageReport_V1(db):
        "ensure the product-usage report exists"

    db.commit()
    return True


if CACHE_USES_POSTGRES:
    # Registered only when CACHE_BACKEND names postgres, so an installation that
    # caches in Redis alone never gains these tables.

    @migration()
    def create_cache_tables_20260921_001(db: TypeDAL) -> bool:
        """Create the tables the Postgres cache backend stores its entries in."""
        db.executesql("""
                      CREATE TABLE cache_entry
                      (
                          id         SERIAL PRIMARY KEY,
                          key        TEXT      NOT NULL UNIQUE,
                          payload    BYTEA     NOT NULL,
                          expires_at TIMESTAMP NULL
                      );
                      """)
        db.executesql("""
                      CREATE TABLE cache_dependency
                      (
                          id    SERIAL PRIMARY KEY,
                          entry INTEGER NOT NULL REFERENCES cache_entry (id) ON DELETE CASCADE,
                          token TEXT    NOT NULL
                      );
                      """)
        # the reverse index: invalidate(gid) is one lookup on this
        db.executesql("CREATE INDEX cache_dependency_token_idx ON cache_dependency (token);")
        db.executesql("CREATE INDEX cache_entry_expires_at_idx ON cache_entry (expires_at);")
        db.commit()
        return True


@migration()
def create_timeline_event_table_20260924_001(db: TypeDAL) -> bool:
    """Create the table for public homepage timeline contributions."""
    db.executesql("""
                  CREATE TABLE timeline_event (
                      id serial PRIMARY KEY,
                      gid uuid NOT NULL DEFAULT uuidv4() UNIQUE,
                      title varchar(500) NOT NULL,
                      source_type varchar(40) NOT NULL,
                      author varchar(500) NOT NULL,
                      event_date date NOT NULL,
                      url varchar(2048) NOT NULL,
                      description text
                  );
                  """)
    db.commit()
    return True


@migration(requires=create_timeline_event_table_20260924_001)
def seed_timeline_events_20260924_002(db: TypeDAL) -> bool:
    """Import the former static homepage timeline."""
    source = Path("/data/seeding/timeline-events.jsonl")
    for line in source.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        db.executesql(
            """
            INSERT INTO timeline_event (title, source_type, author, event_date, url, description)
            VALUES (%(title)s, %(source_type)s, %(author)s, %(event_date)s, %(url)s, %(description)s)
            """,
            placeholders={
                **event,
                "event_date": dt.datetime.strptime(event["event_date"], "%d-%m-%Y").date(),
            },
        )
    db.commit()
    return True


@migration()
def create_catalog_favorites_20260922_001(db: TypeDAL) -> bool:
    """Create effective-dated personal favorites for catalog products and methods."""
    with CatalogFavoriteModelWithPrio_V1(db):
        db.executesql("""
        CREATE TABLE catalog_favorite_ed (
            id            serial PRIMARY KEY,
            gid           uuid        NOT NULL DEFAULT uuidv4(),
            user_gid      uuid        NOT NULL,
            entity_kind   varchar(20) NOT NULL CHECK (entity_kind IN ('product', 'method')),
            entity_gid    uuid        NOT NULL,
            effdt         timestamp   NOT NULL DEFAULT utcnow(),
            effstatus     boolean     NOT NULL DEFAULT TRUE,
            last_saved_by varchar     NOT NULL DEFAULT 'migration/create_catalog_favorites',
            prio          integer     NOT NULL DEFAULT 0,
            sync_gid      uuid        NOT NULL DEFAULT uuidv7()
                CONSTRAINT catalog_favorite_ed_unique_sync_gid UNIQUE,
            created_at    timestamp   NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at    timestamp   NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX catalog_favorite_ed_gid_effdt
            ON catalog_favorite_ed (gid ASC, effdt DESC, id ASC);
        """)
    db.commit()
    return True


@migration(requires=create_catalog_favorites_20260922_001)
def add_catalog_favorite_history_lookup_index_20260922_002(db: TypeDAL) -> bool:
    """Index the per-user history lookup used when restoring a favorite."""
    db.executesql("""
        CREATE INDEX catalog_favorite_ed_user_entity_effdt
            ON catalog_favorite_ed (user_gid, entity_kind, entity_gid, effdt DESC, id DESC);
    """)
    db.commit()
    return True


@migration()
def remove_decision_process_team_model_fk_20260924_001(db: TypeDAL) -> bool:
    """Let the current team model rebuild without deleting decision processes."""
    db.executesql("""
        ALTER TABLE decision_process DROP CONSTRAINT IF EXISTS decision_process_team_gid_fkey;
    """)
    db.commit()
    return True


@migration()
def create_non_imported_products_report_v1_20260930_001(db: TypeDAL) -> bool:
    """Allow reporting on products that never reached product state because of errors.

    Add auxiliary indexes on importer_run and importer_run_event.
    """
    with ImporterRunNonImportedProductsReportV1(db):
        pass
    db.executesql("""
    CREATE INDEX ON importer_run (source, supplier_name, id DESC);
    CREATE INDEX ON importer_run_event (run_gid) WHERE entity_gid IS NULL;
    """)
    db.commit()
    return True


@migration()
def create_edu_v_dashboard_v1_20260930_001(db: TypeDAL) -> bool:
    """Allow reporting on products that never reached product state because of errors.

    Add auxiliary indexes on importer_run and importer_run_event.
    """
    with EduVDashboardReportV1(db):
        pass
    db.commit()
    return True


@migration()
def enable_pg_stat_statements_20261001_001(db: TypeDAL) -> bool:
    """Enable `pg_stat_statements` so slow queries can be inspected.

    Databases created before `postgres/extensions.sql` listed it still need the
    extension here. The view only works once `postgres/addendum.conf` is read
    (`shared_preload_libraries`), but creating the extension itself is harmless.
    """
    db.executesql("CREATE EXTENSION IF NOT EXISTS pg_stat_statements;")
    db.commit()
    return True


@migration(requires=slugify_unregistered_olids_20260915_002)
def backfill_collision_resistant_olids_20261005_001(db: TypeDAL) -> bool:
    """Backfill method OLIDs using new effective-dated versions and existing source metadata."""
    backfill_collision_resistant_olids_v1(db)
    db.commit()
    return True


@migration(requires=create_importer_run_event_20260907_001)
def backfill_importer_run_warnings_20261006_001(db: TypeDAL) -> bool:
    """Backfill historical warnings without changing existing migration units."""
    db.executesql("""
        INSERT INTO importer_run_event (
            run_gid, supplier_gid, supplier_name, event_type, metric,
            entity_type, entity_name, details, created_at, updated_at
        )
        SELECT r.gid,
               r.supplier_gid,
               r.supplier_name,
               'warning',
               LEFT(COALESCE(NULLIF(w.entry ->> 'warning_code', ''), 'warning'), 80),
               CASE WHEN NULLIF(w.entry ->> 'product_name', '') IS NULL THEN 'run' ELSE 'product' END,
               LEFT(w.entry ->> 'product_name', 255),
               w.entry,
               COALESCE(r.finished_at, r.started_at),
               COALESCE(r.finished_at, r.started_at)
        FROM importer_run r
        CROSS JOIN LATERAL json_array_elements(COALESCE(r.warnings_json, '[]'::json))
            WITH ORDINALITY w(entry, position)
        WHERE json_typeof(w.entry) = 'object'
          AND NOT EXISTS (
              SELECT 1 FROM importer_run_event e
              WHERE e.run_gid = r.gid AND e.event_type = 'warning'
          )
        ORDER BY r.id, w.position;
    """)
    with ImporterRunWarningReport_V1(db):
        pass
    db.commit()
    return True


@migration(requires=backfill_importer_run_warnings_20261006_001)
def drop_importer_run_warnings_json_20261006_002(db: TypeDAL) -> bool:
    """Remove the old warning storage after its historical data has been migrated."""
    db.executesql("ALTER TABLE importer_run DROP COLUMN warnings_json;")
    db.commit()
    return True


@migration()
def create_llm_playground_20261008_001(db: TypeDAL) -> bool:
    """Create prompt drafts, activation snapshots and one scenario per scope."""
    db.executesql("""
        CREATE TABLE llm_prompt (
            id serial PRIMARY KEY,
            gid uuid NOT NULL DEFAULT uuidv4() UNIQUE,
            name varchar(120) NOT NULL,
            instructions text NOT NULL,
            created_at timestamp NOT NULL DEFAULT utcnow(),
            updated_at timestamp NOT NULL DEFAULT utcnow()
        );
        CREATE TABLE llm_configuration (
            id serial PRIMARY KEY,
            gid uuid NOT NULL DEFAULT uuidv4() UNIQUE,
            scope_gid uuid,
            model varchar(255) NOT NULL,
            prompt_gid uuid REFERENCES llm_prompt(gid),
            prompt_name varchar(120) NOT NULL,
            instructions text NOT NULL,
            created_at timestamp NOT NULL DEFAULT utcnow(),
            updated_at timestamp NOT NULL DEFAULT utcnow(),
            UNIQUE NULLS NOT DISTINCT (scope_gid)
        );
        CREATE TABLE llm_playground_scenario (
            id serial PRIMARY KEY,
            gid uuid NOT NULL DEFAULT uuidv4() UNIQUE,
            scope_gid uuid,
            context_json json NOT NULL,
            created_at timestamp NOT NULL DEFAULT utcnow(),
            updated_at timestamp NOT NULL DEFAULT utcnow(),
            UNIQUE NULLS NOT DISTINCT (scope_gid)
        );
        INSERT INTO llm_prompt (name, instructions) VALUES (
            'Standaard visieprompt',
            'Je bent een onderwijskundige adviseur die docenten helpt bij het formuleren van
een heldere en concrete visie op leermaterialen.

BELANGRIJK: Gebruik ALLEEN de onderstaande informatie.
Verzin GEEN extra pluspunten, minpunten of andere details die niet expliciet zijn vermeld.

Taak: Schrijf een verbeterde visie die:
1. ALLEEN de hierboven genoemde sterke punten benadrukt
2. ALLEEN de hierboven genoemde aandachtspunten (minpunten) vermeldt
3. Het advies van bestuur en/of school integreert (indien beschikbaar)
4. De huidige visie aanvult en verbetert (indien beschikbaar)
5. Concreet en praktisch toepasbaar is voor docenten
6. Aansluit bij het thema "{theme_label}"

HERHALING: Verzin GEEN extra informatie. Baseer je visie uitsluitend op de hierboven vermelde feiten.

Genereer een professionele, bondige visie in het Nederlands (maximaal 150 woorden).

Vul een JSON-object in met:
- theme: "{theme_label}"
- current_vision: de aangeleverde huidige visie
- improved_vision: jouw gegenereerde visie'
        );
    """)
    db.commit()
    return True


@migration()
def create_catalogus_setting_20261005_001(db: TypeDAL) -> bool:
    """Create reusable catalogue settings and seed the suggestion limit."""
    db.executesql("""
        CREATE TABLE catalogus_setting (
            id serial PRIMARY KEY,
            gid uuid NOT NULL DEFAULT uuidv4() UNIQUE,
            created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
            key varchar(120) NOT NULL UNIQUE,
            value jsonb
        );
        INSERT INTO catalogus_setting (key, value) VALUES ('catalog.similar_material_limit', '9'::jsonb);
    """)
    db.commit()
    return True


@migration(requires=add_catalog_search_session_gid_20260825_001)
def add_catalog_search_recommendation_context_20261005_002(db: TypeDAL) -> bool:
    """Expose recommendation context without mixing it into search analytics."""
    with CatalogSearchReport_V1e(db):
        "ensure the updated report exists"

    db.commit()
    return True


@migration()
def create_faq_tables_20261012_001(db: TypeDAL) -> bool:
    """Create the tables for admin-managed FAQ sections and questions."""
    db.executesql("""
        CREATE TABLE faq_section (
            id serial PRIMARY KEY,
            gid uuid NOT NULL DEFAULT uuidv4() UNIQUE,
            created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
            title varchar(120) NOT NULL,
            sort_order integer NOT NULL DEFAULT 0
        );
        CREATE TABLE faq_question (
            id serial PRIMARY KEY,
            gid uuid NOT NULL DEFAULT uuidv4() UNIQUE,
            created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
            section_gid uuid NOT NULL REFERENCES faq_section (gid) ON DELETE CASCADE,
            question varchar(500) NOT NULL,
            answer text NOT NULL,
            show_on_homepage boolean NOT NULL DEFAULT FALSE,
            sort_order integer NOT NULL DEFAULT 0
        );
        CREATE INDEX faq_question_section_sort_idx ON faq_question (section_gid, sort_order);
    """)
    db.commit()
    return True


@migration(requires=create_faq_tables_20261012_001)
def seed_faq_questions_20261012_002(db: TypeDAL) -> bool:
    """Import the former static FAQ file into admin-managed sections and questions."""
    payload = json.loads(Path("/data/seeding/faq.json").read_text(encoding="utf-8"))
    for section in parse_faq_seed(payload):
        section_gid = str(uuid.uuid4())
        db.executesql(
            """
            INSERT INTO faq_section (gid, title, sort_order)
            VALUES (%(gid)s, %(title)s, %(sort_order)s)
            """,
            placeholders={
                "gid": section_gid,
                "title": section["title"],
                "sort_order": section["sort_order"],
            },
        )
        for question in section["questions"]:
            db.executesql(
                """
                INSERT INTO faq_question (section_gid, question, answer, show_on_homepage, sort_order)
                VALUES (%(section_gid)s, %(question)s, %(answer)s, %(show_on_homepage)s, %(sort_order)s)
                """,
                placeholders={
                    "section_gid": section_gid,
                    "question": question["question"],
                    "answer": question["answer"],
                    "show_on_homepage": question["show_on_homepage"],
                    "sort_order": question["sort_order"],
                },
            )
    db.commit()
    return True


@migration()
def add_signal_service_actor_20261105_001(db: TypeDAL) -> bool:
    """Preserve service identities without storing them in a UUID column."""
    db.executesql("ALTER TABLE signal ADD COLUMN service_actor varchar(255);")
    db.commit()
    return True


@migration(requires=create_faq_tables_20261012_001)
def improve_faq_sort_indexes_20261106_001(db: TypeDAL) -> bool:
    """Index FAQ ordering and the per-section maximum used when adding questions."""
    db.executesql("""
        CREATE INDEX faq_section_sort_idx ON faq_section (sort_order, id);
        CREATE INDEX faq_question_sort_idx ON faq_question (sort_order, id);
        CREATE INDEX faq_question_homepage_sort_idx
            ON faq_question (sort_order, id) WHERE show_on_homepage;
        DROP INDEX faq_question_section_sort_idx;
        CREATE INDEX faq_question_section_sort_idx ON faq_question (section_gid, sort_order, id);
    """)
    db.commit()
    return True


@migration(requires=create_faq_tables_20261012_001)
def restrict_faq_section_deletion_20261106_002(db: TypeDAL) -> bool:
    """Protect questions by allowing only empty FAQ sections to be deleted."""
    db.executesql("""
        ALTER TABLE faq_question DROP CONSTRAINT faq_question_section_gid_fkey;
        ALTER TABLE faq_question ADD CONSTRAINT faq_question_section_gid_fkey
            FOREIGN KEY (section_gid) REFERENCES faq_section (gid) ON DELETE RESTRICT;
    """)
    db.commit()
    return True
