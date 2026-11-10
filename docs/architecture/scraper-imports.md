# Scraper Import Architecture

This document describes how catalogue imports move from an admin action or scheduled job to persisted catalogue data and durable run reporting.

## Entry points

The PGQ scraper consumer is defined in `pgq/consumers/scrapers.py`. The admin helpers in `shared_code/modules/scrapers/admin_imports.py` queue jobs with a UUID job key and pass the supplier and endpoint settings in the payload.

### Supplier imports

The supplier admin action calls `start_import_for_supplier(...)`. It derives the queue entrypoint from `supplier.endpoint_type`:

- `start_importer_edu-v` runs `EduVImporter.run(...)`.
- `start_importer_edu-v-kennisnet`, `start_importer_edu-v-kennisnet-v1`, and `start_importer_edu-v-kennisnet-v2` run `KennisnetCatalogueImporter.run(...)`.
- `start_importer_none` is a no-op entrypoint for the disabled `none` type.

Kennisnet suppliers can be started from the supplier row, but the admin UI warns that this downloads the full Kennisnet catalogue. The preferred action is the aggregate Kennisnet import described below.

### Aggregate and scheduled Kennisnet imports

`start_kennisnet_import(...)` queues `start_importer_edu-v-kennisnet` with `trigger="manual"`. The importer scans the Kennisnet catalogue once for each configured Edu-V version, then distributes the matching publisher rows to the locally configured suppliers.

The single-replica PGQ scheduler queues `import_kennisnet_catalogue_nightly` at 03:00. A scraper worker then runs the same aggregate importer with `trigger="nightly"`.

`refresh_kennisnet_catalogue` is a separate queue entrypoint. It refreshes the local Kennisnet catalogue cache used by the admin catalogue screen; it is not the supplier data import flow and does not create an `importer_run` report.

### Uploaded Edu-V files

The admin test-file workflow previews and validates an uploaded JSON5 document in the web process. Preview is non-persistent. Confirmation revalidates the document and runs `EduVFileImporter.try_import_into_db(...)` synchronously, with the same persistence and run-reporting machinery as queued imports. Its source is `edu-v-file-import`; it is not sent through PGQ.

## Importer contract and flow

`AbstractImporter` in `shared_code/modules/scrapers/abs.py` provides the source-independent lifecycle:

1. `before_import(...)`
2. `import_suppliers(...)`
3. `import_methods_and_products(...)`
4. `after_methods_and_products_import(...)`
5. `import_visions(...)`
6. `sync_images_to_cdn(...)`
7. `after_import(...)`

Importers implement `fetch_suppliers`, `fetch_methods`, `fetch_products`, and optionally `fetch_visions`. They return normalized shared payloads. `ImportFlow` in `shared_code/modules/scrapers/flow.py` validates and persists those payloads, compares effective-dated values, records new/changed/unchanged/skipped/removed/issue outcomes, and can mark missing rows as removed. Product images are copied to image storage when configured.

The standard `run(...)` class method opens the importer database context and injects the service dependencies. `try_import_into_db(...)` wraps the flow, applog events, and durable run recording. A source can extend `after_run_logged(...)` for importer-specific reporting facts.

## Bulk-operation serialization

`AbstractImporter.try_import_into_db(...)` holds one PostgreSQL session-level
advisory lock for its complete lifecycle, including supplier lookup, the
started-run record, removal marking, CDN image updates and run reporting. PGQ
Edu-V and Kennisnet imports (through `run(...)`) and confirmed Edu-V file
uploads use this entrypoint. Imports for different suppliers also
wait for each other: they rebuild the same model tables using `TRUNCATE`.

The reusable `bulk_operation_context(db)` helper in
`shared_code/infra/database/bulk_operations.py` uses the `bulk_operations`
semaphore in the existing `edwh.core` namespace. Other bulk operations that need
mutual exclusion with imports must explicitly use this same context. The lock
is not placed in `rebuild_model()`: imports must wait before acquiring table
locks, not after writing effective-dated rows.

This context owns transaction boundaries. It commits any preceding caller
transaction before waiting, so web-preview read locks cannot block the active
import. Call it only at a bulk-operation boundary where that commit is intended.
The session lock survives intermediate import commits and is released after a
final commit or rollback. A transaction-level advisory lock would be released
too early. SQL failures are rolled back before unlocking, so an aborted
transaction cannot prevent lock cleanup.

The low-level `import_into_db()` and `ImportFlow` methods are lifecycle stages,
not independently locked entrypoints. Production imports must go through
`try_import_into_db()`. Normal interactive edits, materialized-view refreshes,
SQLite catalogue-cache refreshes and migrations do not participate in this
lock; this change serializes imports, not all database activity. Replace the web
processes and all import workers together during rollout: old processes do not
take the lock. No schema migration or PGQ concurrency change is required.

## Edu-V importers

`shared_code/modules/scrapers/eduv/__init__.py` contains the version-specific adapters and the router:

- `EduVImporterV1` supports Edu-V 1.1.0.
- `EduVImporterV2` supports Edu-V 2.0.0.
- `EduVImporter` selects the adapter from `/v1` or `/v2` in the configured endpoint URL.

The adapters fetch either a single products response or all pages when pagination is enabled. They optionally filter rows by publisher, validate rows against the generated versioned schema, normalize products and derived methods, and warn when an endpoint advertises a newer version than the adapter supports.

`EduVFileImporter` reuses the same normalization and persistence flow for an in-memory uploaded payload. It validates the complete file before confirmation and can optionally mark existing supplier rows absent from the file as removed.

### Catalogue scope and product relationships

The shared import flow skips methods and products whose normalized levels are
exclusively primary education (`PO`). Mixed-level records retain their other
levels, with PO removed from level and level-year metadata.

Edu-V product references are resolved to internal GIDs for successor products,
related products and bundle contents. Incoming product GIDs are assigned before
persistence so references can resolve regardless of source row order. Bundle
relationships also determine package/component composition; unresolved bundle
references produce warnings instead of dangling relationships.

## Kennisnet imports

`KennisnetCatalogueImporter` in `shared_code/modules/scrapers/kennisnet_import.py` is an `AbstractImporter` implementation with two scopes:

- With `supplier_gid`, it imports one selected Kennisnet supplier.
- Without `supplier_gid`, it imports all configured Kennisnet suppliers as one aggregate run.

For each supported Kennisnet endpoint version, it performs one paginated catalogue scan, groups rows by publisher, and passes the matching rows through `EduVPayloadImporter`. It also records publisher coverage observations (`imported`, `own_endpoint`, `unconfigured`, or `unknown`) and supplier-level method/product outcomes. These facts are stored as additional `ImporterRunEvent` rows after the run record is created.

## Persistence and run reporting

`ImportFlow` persists current model rows and effective-dated rows for suppliers, methods, products, and visions. Import priorities distinguish importer data from human-written data, and removal marking is scoped to the supplier or suppliers in the run.

Each completed attempt is recorded by `record_importer_run(...)` in `shared_code/modules/scrapers/run_log.py`:

- `importer_run` stores source, endpoint and supplier identity, job key, timestamps, duration, success/failure state, and payload metadata. Warnings are stored only as events.
- `importer_run_event` stores metric events, row/entity outcomes, error events, and warning events. Metrics include the usual seen/new/changed/unchanged/skipped/removed/issue counters, auxiliary supplier/vision counts, image-upload counts, and importer-specific Kennisnet facts.
- Error event details include the error code and, where available, entity identifiers, validation status, and source-row details.

Runs for a supplier are retained up to `DEFAULT_RUN_RETENTION` (20) newest runs. Aggregate runs without a `supplier_gid` are not pruned by `_prune_old_runs(...)`, so the Kennisnet history can retain those reports for the admin history view.

## Errors, warnings, and observability

- Importers register non-fatal warnings through `_warn_import(...)` or `ImportStats.warning_stats`. They become `importer_run_event` rows with `event_type="warning"` and the warning code in `metric`. Supplier and entity identity are explicit event fields; diagnostic messages, reasons, full product names, and source URLs follow the `ImportWarningDetails` contract in `modules/scrapers/warnings.py`. The admin UI still displays a successful run with warnings as incomplete.
- Warning facts stay in memory until run finalization, where they are persisted in the same transaction as the outcome. Finalizing the same run again replaces its warning snapshot instead of appending duplicates. Warnings collected before a failure are recorded after rollback; this is reporting, not an independently committed live audit stream.
- `ImporterRun.warnings` is a filtered event relationship. `ImporterRun.warnings_json` is a computed presentation property, not a database field. Admin readers join the warning relationship before serializing multiple runs; supplier badges use an existence query.
- Row-level validation and persistence problems become `importer_run_event` error rows and are reflected in the run metrics.
- If the import raises an exception, the database work is rolled back. The failure is then recorded as a `success=False` run with `failure_message` when run-record persistence is still possible, and the exception is re-raised to the queue or web caller.
- `scraper-import-started`, `scraper-import-finished`, and `scraper-import-failed` events are sent through applog. The failure event includes the formatted exception message.

### Warning storage rollout

Migration `backfill_importer_run_warnings_20261006_001` copies historical warning objects to events in their original order. It retains the complete original object in `details`, including unknown codes and names that exceed the indexed display-field lengths. Historical aggregate warnings have no reliable supplier or entity identifiers, so the migration does not infer them from text. New Kennisnet warnings retain the originating supplier before deduplication. Migration `drop_importer_run_warnings_json_20261006_002` then removes the old column. There are no legacy runtime readers or writers.

The migration also creates `importer_run_warning_stat`, a versioned reporting view available to the live Superset warning datasets. The view reads warning events only. Files under `./superset/` are read-only exports and must not be edited or treated as deployable dataset definitions.

Update the live `SIVON fouten per import-run` dataset to join the reporting view instead of expanding `warnings_json`:

```sql
SELECT importer_run.*, w.message, w.warning_code
FROM importer_run
JOIN importer_run_warning_stat w ON w.run_gid = importer_run.gid;
```

In the live `Sivon import runs` dataset, replace the JSON array length expression with the following expression, preserving the rest of its query:

```sql
(SELECT count(*) FROM importer_run_warning_stat w WHERE w.run_gid = ir.gid) AS aantal_warnings
```

Stop old import workers and coordinate migration, application/worker replacement, and these live Superset dataset changes. Old application versions and dashboard queries referencing the removed column will fail after the migration, so replace them as part of the same rollout. No catalogue reimport is needed.
