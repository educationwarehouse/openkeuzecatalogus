# Effective-Dated Models

This project stores several domain entities in two related database objects:

- `<name>_ed`: the effective-dated source table with history rows
- `<name>_model`: the current-state projection used by the application

Current examples:

- `product_ed` -> `product_model`
- `supplier_ed` -> `supplier_model`
- `method_ed` -> `method_model`
- `vision_ed` -> `vision_model`

## Why This Exists

The `_ed` table keeps an append-oriented record of changes over time.
The `_model` table keeps exactly one currently active row per logical entity `gid`.

This gives the project both:

- history and sync traceability in `_ed`
- simple "current truth" reads from `_model`

## `_ed` Table Semantics

`_ed` tables are the source of truth for imported or synchronized records.
They typically contain:

- `gid`: stable logical entity id
- `effdt`: effective timestamp for when a row becomes active
- `effstatus`: whether the row is active
- `prio`: precedence for rows that compete for the same `gid`
- `sync_gid`: stable row-level sync/upsert key
- domain fields such as `name`, `olid`, `description`, and related foreign gids

The shared effective-dating field mixin lives in [shared_code/data_model/mixins/effdt.py](../../shared_code/data_model/mixins/effdt.py).

## `_model` Table Semantics

`_model` tables are derived tables created by migrations.
They are not independent authoring tables.

For each `gid`, the selected row is the best active `_ed` row where:

- `effdt <= now()`
- `effstatus = true`
- highest `prio` wins first
- newest `effdt` wins next

That selection logic is implemented by `get_active_<name>(...)` and the shared helper `create_effdted_model_view_with_prio_v4(...)` in [shared_code/migrations/migration_support/core.py](../../shared_code/migrations/migration_support/core.py).

## Update Flow

Creation and maintenance happen in migrations:

1. Create `<name>_ed`.
2. Create `<name>_model` with the same base structure.
3. Create `get_active_<name>()` to resolve the current best row.
4. Create an insert trigger on `<name>_ed`.
5. On each inserted history row, refresh only the affected logical record in `<name>_model`.
6. Rebuild the full `<name>_model` table after bulk changes when needed.

The helper rebuild function is `rebuild_<name>_model()`.
Bulk rebuild of all model tables is handled by `rebuild_all_materialized_tables_v1(...)`.

## Read/Write Rule

- Write history and synchronized changes into `_ed`.
- Read current application state from `_model`.

In Python table definitions this appears as:

- `ProductEd`, `SupplierEd`, `MethodEd`, `VisionEd` mapped to `_ed`
- `Product`, `Supplier`, `Method`, `Vision` mapped to `_model`

See [shared_code/data_model/setup.py](../../shared_code/data_model/setup.py).

## Practical Guidance

- If you need current rows for normal app behavior, query `_model`.
- If you need historical, sync, or precedence data, inspect `_ed`.
- If a bulk operation bypasses normal incremental updates, rebuild the model tables afterward.
