# Migrations (`edwh migrate`)

This project runs database migrations through [edwh-migrate](https://github.com/educationwarehouse/migrate) inside the Compose `migrate` service.

`migrate/` (repo root) and `shared_code/migrations/` are two different things:

- `migrate/` is the Compose service definition: `Dockerfile`, `requirements.txt`, and the bind-mounted `data/` (restore snapshots) and `flags/` (lock files) directories. It has no migration logic of its own.
- `shared_code/migrations/migrations.py` is the actual migration registration file (`MIGRATIONS_FILE`, see below); this is where `@migration()`-decorated functions live.

## Where Migrations Run

- In Docker Compose, the `migrate` service runs `command: migrate`.
- `py4web` and PGQ workers wait for `migrate` to complete successfully before starting.
- Shared migration coordination state is bind-mounted at `./migrate/flags` (container path: `/flags`).

## Configuration Used by `edwh-migrate`

Key environment settings used in this repo:

- `MIGRATE_URI`: database connection used by migration tooling.
- `SCHEMA_VERSION`: used for the migration lock file name. It is a hash of `shared_code/`, and it also serves as the cache build id (see [Caching](../architecture/caching.md#keys)).
- `MIGRATIONS_FILE`: points to migration registration file (here: `/pythonpath/shared_code/migrations/migrations.py`).
- `DB_FOLDER`: local DAL folder (`/tmp` in this setup).
- `USE_TYPEDAL`: enables `TypeDAL` during migrations.

Default recovery input file path is:

- `/data/database_to_restore.sql` (mapped from `./migrate/data` on host).

## CLI Flags

`edwh-migrate` console hook supports:

- `-h`, `--help`: print help and usage notes.
- `-l`, `--list`: list discovered migrations with status from `ewh_implemented_features`.

Normal run (no flags) imports migrations and executes pending ones.

## Lock-File Behavior (`/flags`)

Lock file pattern:

- `/flags/migrate-<SCHEMA_VERSION>.complete`

Behavior:

- If lock file already exists, migrate exits successfully without rerunning.
- If lock file does not exist, migrations run.
- After successful migration run, lock file is created.
- If migration fails, lock file is removed (or kept absent) so retry is possible.
- If `SCHEMA_VERSION` is missing, lock-file checks are skipped.

Operational note:

- `edwh setup` ensures ownership/permissions for `migrate/flags`.

## `database_to_restore.sql` Recovery Flow

When the migration system connects to the DB and detects an uninitialized migration table, it tries restore before “start from scratch”.

Restore file discovery starts from configured `database_to_restore` base path and checks these variants in order:

1. `.sql`
2. `.sql.gz`
3. `.gz`
4. `.sql.xz`
5. `.xz`

Given default path `/data/database_to_restore.sql`, practical files are:

- `/data/database_to_restore.sql`
- `/data/database_to_restore.sql.gz`
- `/data/database_to_restore.gz`
- `/data/database_to_restore.sql.xz`
- `/data/database_to_restore.xz`

Decompression/pipe behavior:

- `.sql` -> `cat ... | psql <MIGRATE_URI>`
- `.gz` / `.sql.gz` -> `zcat ... | psql <MIGRATE_URI>`
- `.xz` / `.sql.xz` -> `xzcat ... | psql <MIGRATE_URI>`

After restore (Postgres), it sets:

- `SET search_path TO <schema>` (default schema config is `public` unless overridden).

If no restore file exists:

- migration tooling attempts to initialize from scratch with DAL migration enabled.

## Migration Source and Execution Rules

- Migrations are registered via `@migration()` decorators in the configured migrations file.
- Applied migration status is stored in `ewh_implemented_features` table.
- Failed migration functions are recorded as failed and can be retried on next run.
- Optional dependency ordering (`requires=[...]`) is respected by the migration store.

## Seed Data Migration (Old Server JSON)

- Migration `seed_data_from_old_server_json_20260526_001` optionally imports seed rows from old-server JSON endpoints.
- Configure:
    - `MIGRATE_SEED_BASE_URL`
    - `MIGRATE_SEED_BEARER_TOKEN`
- Tests import the same seed tables only when `MIGRATE_SEED_CATALOG_CONFIGURATION=1`; their
  `MIGRATE_SEED_BASE_URL` must use a local `file://` URL.
- Endpoint convention used by this migration:
    - `{MIGRATE_SEED_BASE_URL}/seed/product_ed`
    - `{MIGRATE_SEED_BASE_URL}/seed/supplier_ed`
    - `{MIGRATE_SEED_BASE_URL}/seed/method_ed`
    - `{MIGRATE_SEED_BASE_URL}/seed/vision_ed`
- Rows are upserted by `sync_gid`.

## Standard School Subjects

The schema and seed migrations add effective-dated school subjects: 344 standard names and
70 aliases from the 2026-2027 v1.01 values list, including vocational subjects.
[Seed data](../../migrate/data/seeding/school_subjects_2026_2027_v1.json) loads from `/data/seeding`.
Keep this snapshot unchanged; corrections require a new migration inserting effective-dated versions.

## Supplier RBAC Seeding

Supplier access is data-driven rather than env-var driven.

- Migration `setup_supplier_rbac_groups_20260618_002` seeds special supplier rows when they are missing.
- The seeded suppliers are `Education Warehouse` and `SIVON`.
- Each supplier gets a matching RBAC identity in the form `<supplier gid>@supplier`.
- All supplier identities inherit from `supplier@internal`.
- The seeded Education Warehouse and SIVON suppliers also inherit from `admin@internal`.
- Runtime login and email-verification hooks then match the user's email domain against `supplier_ed.email_domains` and grant the corresponding supplier membership.

For the runtime flow, see [Supplier memberships and access control](../architecture/supplier-memberships.md).

## Organisation RBAC and Permission Backfill

Organisation access is also data-driven.

- Migration `create_organisation_ed_20260622_001` creates the effective-dated organisation source table and current model table.
- Migration `setup_organisation_rbac_groups_20260622_002` ensures the base RBAC groups exist:
    - `users@internal`
    - `organisation@internal`
    - `board@internal`
    - `school@internal`
    - `location@internal`
- Organisation rows create or update their own RBAC identities in the form `<organisation gid>@organisation`.
- Migration `seed_organisation_data_from_old_server_json_20260622_003` can import organisation rows and relations from old-server JSON endpoints.
- Migration `backfill_organisation_rbac_permissions_20260623_001` converts seeded organisation hierarchy relations into explicit RBAC permissions.

Runtime login and email-verification hooks also match the user's email domain against `organisation_ed.email_domains` and grant the corresponding organisation membership.

For the runtime and policy model, see [Auth and RBAC](../architecture/auth-rbac.md).

## Troubleshooting

- Migrate exits immediately but app starts:
    - Check if `/flags/migrate-<SCHEMA_VERSION>.complete` already exists.
- App/worker services stay down waiting for migrate:
    - Inspect `migrate` logs and verify DB reachability and `MIGRATE_URI`.
- Restore expected but not happening:
    - Confirm file is in `./migrate/data` and named as one of the supported variants.
- Re-run intentionally with same schema version:
    - Remove the matching `.complete` lock file in `./migrate/flags` first;
- You can also run `edwh migrate --force` to automatically remove those flag files before migrating.

## Writing a New Migration

### Naming and Placement

- Function name: `descriptive_name_YYYYMMDD_NNN` (for example `create_supplier_ed_20260521_001`).
- The date suffix makes migrations chronologically identifiable; `_NNN` is the sequence number within that day.
- Keep names unique across the whole file; the full function name is the identity stored in `ewh_implemented_features`.
- **Append new migrations at the end of `migrations.py`.** With the default ordering mode, execution order follows definition order in the file, not the date in the name. The date suffix documents intent; file position guarantees order.
- The helper migration `create_utcnow_helper_20060000_001` combines both guarantees: it is first in the file _and_ uses a date far in the past, so it sorts before all dated migrations under either ordering mode.

### Function Skeleton

```python
@migration()
def do_something_20260728_001(db: TypeDAL) -> bool:
    """One-line summary of the schema change."""
    db.executesql("""
                  ALTER TABLE ...
                  """)
    db.commit()
    return True
```

- Decorate with `@migration()` (or `@migration`); both register the function.
- Every migration receives `db: TypeDAL`, ends with `db.commit()`, and returns `True` on success.
- Keep the docstring to one line describing the _why_; multi-line only when columns or behavior need explanation.
- Reusable logic belongs in `shared_code/migrations/migration_support/`, not inline in `migrations.py`. Add a per-entity module there when a new entity family needs one.

### SQL Conventions

- Pass dynamic values with `%(name)s` placeholders and `placeholders=dict(...)`; never with f-string interpolation (see [Database](database.md)).
- T-strings (`t"SELECT ... WHERE gid = {gid}"`) are an accepted alternative for parameterized values.
- F-strings are only acceptable for SQL _identifiers_ (table, role, index names) from controlled sources, annotated with `# noqa S608` (see `create_superset_readonly_user_20260622_001`).
- Do not make migrations defensively idempotent. A migration runs once; on failure it is recorded as failed and retried on the next run. Plain `CREATE TABLE` is preferred so conflicts surface as errors.
- Use `IF NOT EXISTS` only when the object can legitimately pre-exist (example: the applog tables shared with the ontwikkelstraat, or roles in a test environment).
- Index naming: `idx_<table>_<purpose>` for lookup indexes, `<table>_<columns>` for supporting indexes, `<table>_<column>_unique` for unique indexes. Unique constraints on `_ed` tables are named `<table>_unique_sync_gid`.

### Effective-Dated Tables (`_ed`)

For the semantics, see [Effective-dated models](../architecture/effective-dated-models.md). When creating a new `_ed` source table, follow the standard shape:

- Standard columns: `id serial PRIMARY KEY`, `gid uuid NOT NULL DEFAULT uuidv4()`, `effdt timestamp DEFAULT utcnow()`, `effstatus boolean DEFAULT TRUE`, `prio integer DEFAULT 0`, `last_saved_by varchar`, `created_at`/`updated_at timestamp DEFAULT CURRENT_TIMESTAMP`.
- `sync_gid uuid DEFAULT uuidv7() NOT NULL` with `CONSTRAINT <table>_unique_sync_gid UNIQUE` — this is the row-level upsert key for sync/import.
- Standard indexes:
    - `<table>_id_effdt ON <table> (gid ASC, effdt DESC, id ASC)`
    - `idx_<table>_effdt_lookup ON <table> (effdt DESC, gid ASC, prio DESC, effdt DESC) INCLUDE (id)`
- Wrap the `CREATE TABLE` in the matching model manager (`with ProductModelWithPrio_V1(db):`) so the `_model` projection is created alongside.

### View and Model Managers (`ViewMigrationManager`)

All `ViewMigrationManager` subclasses share the same lifecycle: entering the `with` block runs `down()` (drop), leaving it runs `up()` (recreate). Two families exist.

**Model managers** for effective-dated pairs: `ProductModelWithPrio_V1`, `SupplierModelWithPrio_V1`, `MethodModelWithPrio_V1`, `VisionModelWithPrio_V1`, `TaggedModelWithPrio_V1`, `OrganisationModelWithPrio_V1` (importable from `shared_code.migrations.migration_support`).

Use `with <Entity>ModelWithPrio_V1(db):` around **any DDL that alters the `_ed` table** (adding/dropping columns, changing types). `up()` recreates the `_model` table via `create_effdted_model_view_with_prio_v4`, its indexes, and refills it.

**Report managers** for standalone (materialized) views: for example `CatalogSearchReport_V1`, `LocationsWithoutOrganisationMappingReport_V1` (in `migration_support/catalog_search_report.py` and `migration_support/school_data_quality_reports.py`, imported directly from their module).

Use them with an empty block to create or rebuild the view:

```python
@migration()
def create_catalog_search_report_20260713_005(db: TypeDAL) -> bool:
    """Create the materialized report for catalog search activity."""
    with CatalogSearchReport_V1(db):
        pass
    db.commit()
    return True
```

**Manager versioning.** When a view definition changes, do not edit the existing manager class. Add a suffixed class with the new definition, and set `until` on the old class to the migration that introduces its successor. The suffix indicates the nature of the change:

- **`_V1b`, `_V1c`, ...**: non-breaking changes to the same database object. The view or function name stays the same; the Python class version tracks the evolution of the definition. Use this when adding a column, changing a WHERE clause, or otherwise modifying the query without renaming the database object.
- **`_V2`, `_V3`, ...**: breaking changes that also rename the database object (for example `some_view_v1` → `some_view_v2`). Use this when the query shape or output schema changes so fundamentally that downstream consumers need to adapt.

The manager attributes controlling lifecycle:

- `since`: migration that must have run before this manager becomes active (for model managers: the migration creating the `_ed` table). The manager is a no-op before that point.
- `until`: migration after which this manager must no longer act. The old version is a no-op once its successor migration has run.
- `uses`: the managers this view depends on (for example a report reading from `organisation_model`). When a dependency is rebuilt, this view is torn down first and rebuilt after, so it always reflects the refreshed dependency.

This keeps dependent trigger/function/model structures consistent with altered source tables, and old migrations replayable, without hand-written teardown.

### Bulk Operations

- Use `with no_triggers(db):` around bulk inserts/updates on `_ed` tables. It sets `session_replication_role = replica`, so the per-row `_model` refresh trigger is skipped.
- **After a `no_triggers` bulk operation, always rebuild**: `rebuild_all_materialized_tables_v1(db)`. Pass `extra=["recursive_tables"]` when organisation hierarchy tables are affected, or `dependency_order=[...]` when rebuild order matters.
- Use `simple_progress(rows)` when iterating large batches so migration logs show progress. It is a minimal progress counter (a "poorman's tqdm") that prints coarse updates (every 1000 rows) to stderr; it does not support live-updating progress bars, and in Docker Compose `migrate` containers the stderr output may be buffered or delayed because of the container's stdout streaming setup.

### Dependencies

- Use `@migration(requires=other_migration_function)` when execution order cannot be guaranteed by file position alone, for example a cross-domain dependency (see `create_superset_readonly_user_20260622_001`).
- `requires` accepts a function reference or a function name; prefer the function reference so renames fail loudly.

### Environment-Dependent Migrations

- Migrations that depend on optional environment configuration must **skip gracefully**: check the variable, print `[migrate] ...` and `return True` (see `seed_data_from_old_server_json_20260526_001`). Skipping counts as success and is recorded as such.
- Migrations with a hard requirement may read `os.environ[...]` directly; a missing variable then fails the migration and it is retried on the next run (see `create_superset_readonly_user_20260622_001`). Choose deliberately between the two patterns.
- A migration for an optional feature can instead be **registered conditionally**, under a module-level `if` (see `create_cache_tables_20260921_001`, registered only when `CACHE_BACKEND` names `postgres`). Unlike skipping, nothing is recorded while the condition is false, so the migration still runs once the condition holds. Changing `.env` doesn't change `SCHEMA_VERSION`, though, so migrate won't run again on its own: remove `/flags/migrate-<SCHEMA_VERSION>.complete` and run it. The test commands put `CACHE_BACKEND=postgres` in their baseline environment (`default_testing_env()` in `test.tasks.py`) so the migration keeps getting exercised.

### Helper Inventory

Importable from `shared_code.migrations.migration_support`:

| Helper                                                                           | Purpose                                                                                         |
| -------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `create_effdted_model_view_with_prio_v4(db, table)`                              | Create `_model` table, `get_active_<table>()`, triggers, `rebuild_<model>()` for an `_ed` table |
| `upsert_index_v1(db, table, columns, unique=, include=)`                         | Drop and recreate an index named `idx_<table>_<columns>`                                        |
| `drop_table_or_mv(db, name)`                                                     | Drop a table or materialized view, whichever exists                                             |
| `no_triggers(db)`                                                                | Context manager: disable triggers for bulk operations                                           |
| `rebuild_all_materialized_tables_v1(db, exceptions=, extra=, dependency_order=)` | Rebuild all `*_model` tables                                                                    |
| `simple_progress(items, every=1000)`                                             | Yield items with progress output for large batches                                              |
