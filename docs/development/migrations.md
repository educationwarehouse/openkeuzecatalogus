# Migrations (`edwh migrate`)

This project runs database migrations through [edwh-migrate](https://github.com/educationwarehouse/migrate) inside the Compose `migrate` service.

## Where Migrations Run

- In Docker Compose, the `migrate` service runs `command: migrate`.
- `py4web` and PGQ workers wait for `migrate` to complete successfully before starting.
- Shared migration coordination state is bind-mounted at `./migrate/flags` (container path: `/flags`).

## Configuration Used by `edwh-migrate`

Key environment settings used in this repo:

- `MIGRATE_URI`: database connection used by migration tooling.
- `SCHEMA_VERSION`: used for the migration lock file name.
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
- Endpoint convention used by this migration:
  - `{MIGRATE_SEED_BASE_URL}/seed/product_ed`
  - `{MIGRATE_SEED_BASE_URL}/seed/supplier_ed`
  - `{MIGRATE_SEED_BASE_URL}/seed/method_ed`
  - `{MIGRATE_SEED_BASE_URL}/seed/vision_ed`
- Rows are upserted by `sync_gid`.

## Troubleshooting

- Migrate exits immediately but app starts:
  - Check if `/flags/migrate-<SCHEMA_VERSION>.complete` already exists.
- App/worker services stay down waiting for migrate:
  - Inspect `migrate` logs and verify DB reachability and `MIGRATE_URI`.
- Restore expected but not happening:
  - Confirm file is in `./migrate/data` and named as one of the supported variants.
- Re-run intentionally with same schema version:
  - Remove the matching `.complete` lock file in `./migrate/flags` first.
