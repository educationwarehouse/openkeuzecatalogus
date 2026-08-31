# Catalogue Filtering

This project uses persisted metadata to drive public catalogue filters for products and methods.
The runtime reads filter definitions from `dynamic_filter`, turns them into request filters, and applies the active ones to the public listing query.

## Filter Flow

1. Load active `dynamic_filter` rows ordered by `sort_order` and `id`.
2. Keep only rows that apply to the current entity kind (`product`, `method`, or `both`).
3. Build a concrete filter definition from the metadata.
4. Parse request values into active filter state.
5. Apply the active filters to the base public query.

The public listing modules use this flow through `CatalogFilters.resolve(...)` and `CatalogFilters.apply(...)`.

## Supported Filter Kinds

### `search`

Free-text search backed by the table search mixin.

- Used for the `q` filter.
- Reads the first non-empty request value.
- Applies the table's search implementation instead of a field-specific comparison.
- Renders as a search input.

### `dynamic`

Generic field-based filtering.

- Requires `field_name` to point at a real field on the target table.
- Uses `match_mode` to decide how values are compared.
- Renders as either a select or a multi-select widget, depending on the field type.

Scalar fields default to exact membership filtering.
List fields are treated as multi-select filters and accept multiple values.

### `custom`

Special-case filter handlers for non-standard behavior.

- Requires both `field_name` and `handler_key`.
- The handler must be registered in the catalogue filter module.
- Used when a filter needs custom parsing or query logic.

The current custom handler is `has_value`, which keeps rows where the configured field is not empty.

## Metadata Fields

The `dynamic_filter` table stores the following configuration:

- `slug`: querystring key and filter identifier.
- `label`: human-readable label shown in the UI.
- `filter_kind`: `search`, `dynamic`, or `custom`.
- `field_name`: field bound to the filter for dynamic and custom filters.
- `match_mode`: `contains` or `belongs` for dynamic filters.
- `applies_to`: `product`, `method`, or `both`.
- `handler_key`: custom handler identifier.
- `widget_kind`: preferred control type for rendering.
- `is_active`: enables or disables the filter.
- `sort_order`: display ordering.

## Request Semantics

- Search filters use the first non-empty request value.
- Scalar dynamic filters use the first non-empty request value.
- List-field dynamic filters normalize, deduplicate, and preserve request values in order.
- `match_mode = contains` uses substring matching for dynamic fields.
- `match_mode = belongs` uses exact membership matching.
- Checkbox filters are active when the parameter is present.

## Seeded Filters

The initial migration seeds these filters:

- `q`: free-text search for both products and methods.
- `levels`: shared catalogue filter for education levels.
- `subjects`: shared catalogue filter for subject areas.
- `composition`: product-only filter for composition.
- `demo`: product-only "has value" filter for demo environments.
- `preview`: method-only "has value" filter for digital previews.
- `samples`: method-only "has value" filter for sample copies.

## Extending The System

To add a new filter:

1. Create or update a `dynamic_filter` row.
2. Choose the right `filter_kind`.
3. Set `field_name`, `match_mode`, `applies_to`, and `widget_kind` as needed.
4. For custom behavior, add a handler to the catalogue filter module and reference it via `handler_key`.

Keep the filter metadata as the source of truth so rendering and request handling stay aligned.
