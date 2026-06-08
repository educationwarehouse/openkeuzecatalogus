"""Registered database migrations."""

import os

import requests
from edwh_auth_rbac import migrations as _
from edwh_migrate import migration
from pgskewer import migrations as _  # noqa F401 - importing exposes these migrations
from typedal import TypeDAL

from shared_code.migrations.migration_support import (
    MethodModelWithPrio_V1,
    ProductModelWithPrio_V1,
    SupplierModelWithPrio_V1,
    VisionModelWithPrio_V1,
    no_triggers,
    rebuild_all_materialized_tables_v1,
)
from shared_code.migrations.migration_support.seeding import import_seed_table_v1


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
                                                  method_gid            uuid,
                                                  supplier_gid          uuid,
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
                                                  effdt                 timestamp,
                                                  effstatus             boolean,
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
                                                   effdt          timestamp,
                                                   effstatus      boolean,
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
                                                 supplier_gid                uuid,
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
                                                 effdt                       timestamp,
                                                 effstatus                   boolean,
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
                                                 effdt              timestamp,
                                                 effstatus          boolean,
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
            ON public.evidence ((source->>'gid'));

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
        """
    )
    db.commit()
    return True
