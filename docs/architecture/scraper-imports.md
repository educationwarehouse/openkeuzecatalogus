# Scraper Import Architecture

This document describes how supplier imports run from admin trigger to durable run reporting.

## Entry Points

Two entrypoint layers are used:

- Admin trigger (`apps/admin`): `start_import_for_supplier(...)` enqueues a PGQ job.
- Worker trigger (`pgq-scrapers`): `pgq/consumers/scrapers.py` handles queue entrypoints.

Current queue entrypoints:

- `start_importer_edu-v` -> runs `EduVImporter.run(...)`.
- `start_importer_none` -> no-op placeholder.

## Importer Contract

`AbstractImporter` (`shared_code/modules/scrapers/abs.py`) defines the import lifecycle:

1. `before_import(...)`
2. `import_suppliers(...)`
3. `import_methods_and_products(...)`
4. `after_methods_and_products_import(...)`
5. `import_visions(...)`
6. optional `sync_images_to_cdn(...)`
7. `after_import(...)`

Importers return normalized shared structures (`ImportMethod`, `ImportProduct`, etc.) that are then persisted by shared flow helpers.

## Persistence and Run Reporting

Persistence helpers in `shared_code/modules/scrapers/flow.py` handle upsert/update/remove bookkeeping for effective-dated tables and current model tables.

Each run writes durable reporting rows through `record_importer_run(...)` in `shared_code/modules/scrapers/run_log.py`:

- `importer_run`: run-level metadata (success, duration, payload, warning/failure fields).
- `importer_run_count_stat`: aggregated count metrics (seen/new/changed/removed/etc.).
- `importer_run_error_stat`: grouped error-code statistics for import issues.

Retention is enforced per supplier (`_prune_old_runs(db, supplier_gid, keep_last)`) by pruning older run rows.

## Error and Warning Model

- Importers can register non-fatal warnings through `_warn_import(...)`.
- Run status is still `success=True` when warnings exist, but UI marks these runs as incomplete.
- On exceptions, run metadata is still persisted with `success=False` and `failure_message`.
- Import start/finish/failure events are sent via applog for observability.

## Edu-V Specifics

`shared_code/modules/scrapers/eduv/__init__.py` contains version-aware importers:

- `EduVImporterV1`
- `EduVImporterV2`
- `EduVImporter` (router/facade)

This keeps wire-format differences in importer adapters while preserving one shared persistence/reporting flow.
