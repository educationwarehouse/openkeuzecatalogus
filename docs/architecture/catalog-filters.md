# Catalogue Filtering

This project uses persisted metadata to drive public catalogue filters for products, packages and methods.
The runtime reads filter definitions from `dynamic_filter`, turns them into request filters, and applies the active ones to the public listing query.

## Filter Flow

1. Load active `dynamic_filter` rows ordered by `sort_order` and `id`.
2. Keep only rows that apply to the current catalogue tab. `package` has its own
   configuration; `both` continues to mean products and methods.
3. Build a concrete filter definition from the metadata.
4. Parse request values into active filter state.
5. Apply the active filters to the base public query.

The public listing modules use this flow through `CatalogFilters.resolve(...)` and `CatalogFilters.apply(...)`.

### Asynchronous option lists

Catalogue dropdowns fetch options through `/htmx/catalog-filter-options/<entity_kind>/<slug>`.
The endpoint supports text search (`q`) and pagination (`offset`, `limit`, at most
100 options per page), so large lists do not need to be rendered into every page.
Selected values remain in the form while visitors search or load another option
page. The private recommendation form retains `/htmx/filter-options/<entity_kind>/<slug>`
with its existing product scope, including packages and its composition filter.

## Supported Filter Kinds

### `search`

Free-text search backed by the table search mixin.

- Used for the `q` filter.
- Reads the first non-empty request value.
- Applies the table's search implementation instead of a field-specific comparison.
- Renders as a search input.

For products and methods that search implementation is relevance-ranked: the result order comes
from configurable weights stored in the database, not from the filter definition.
See [Search ranking](search-ranking.md).

### `dynamic`

Generic field-based filtering.

- Requires `field_name` to point at a real field on the target table.
- Uses `match_mode` to decide how values are compared.
- Renders as either a select or a multi-select widget, depending on the field type.

Scalar fields default to exact membership filtering.
List fields are treated as multi-select filters and accept multiple values.

#### School subjects

`subjects` filters match standard names and aliases from `school_subject_model` after trimming
and casefolding, preserving supplier data. Unknown or ambiguous names remain selectable.
Dropdown searches also match aliases.

Manage names and aliases at `/admin/school-subjects`. Its **Ongekoppelde vakken** button opens
the usage overview, where admins can match source names to existing subjects or create new ones.

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
- `applies_to`: `product`, `package`, `method`, or `both` (products and methods).
- `handler_key`: custom handler identifier.
- `widget_kind`: preferred control type for rendering.
- `is_active`: enables or disables the filter.
- `sort_order`: display ordering.

The package catalogue uses the `Product` model with `composition = package`, while
the product catalogue uses `composition = single`. Filter options use that same
restriction, and composition filters are excluded from both tabs.

Migration `add_package_catalog_configuration_20261103_001` copies the current
product/shared filter and sort settings into new package records, excluding the
composition filter. Subsequent edits are independent. The V2 migration managers
make filter and sort slugs unique per `applies_to` scope so both tabs can retain
the same querystring keys. Existing effective-dated settings remain untouched.

Migration `add_product_family_name_20261103_002` changes the existing product and
package method filters to exact, multi-select matching on `product_family_name`.
The nullable product field stores Edu-V's `productFamilyName`, with surrounding
whitespace removed and no fallback to the product name. Existing products remain
`NULL` until a new import supplies the value; no product data is backfilled.
Empty family names are omitted from the options. Method derivation and the
`method_gid` relationship continue unchanged.

## Request Semantics

- Search filters use the first non-empty request value.
- Scalar dynamic filters use the first non-empty request value.
- List-field dynamic filters normalize, deduplicate, and preserve request values in order. A row
  matches when its list field shares at least one selected value; the catalogue-overlap
  recommender uses the same matching rule.
- `match_mode = contains` uses substring matching for dynamic fields.
- `match_mode = belongs` uses exact membership matching.
- Checkbox filters are active when the parameter is present.

## Option Caching

`CatalogFilters.resolve(...)` caches the option lists per entity kind
(`catalog_filter_options`, public scope, 300 seconds), separating catalogue tabs
from the unrestricted recommendation filters, through the
[cache service](caching.md). Only the option queries are saved: filter
definitions are still read on every request.

Options are built from `option_builder` before any active value narrows it, so
one entry serves every request for that entity kind. Active values are parsed
from the request rather than queried, so they don't vary the key.

A filter added after an entry was written loads its own options instead of
coming back empty. Filter configuration and option queries record cache
dependencies; business-model writes and explicit invalidation for raw SQL or
view refreshes clear affected entries. Subject-list changes also invalidate filter options
and public product/method listing caches. The 300-second TTL bounds staleness if
invalidation fails. Invalidation currently runs before commit for Redis and
memory, so concurrent reads can still refill an entry with pre-commit data; see
[invalidation limitations](caching.md#dependencies-and-invalidation).

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
