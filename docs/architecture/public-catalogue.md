# Public Catalogue Pages

The public catalogue is served by `py4web/apps/_default`. Its overview pages use
HTMX endpoints for filtering and results, while detail and comparison pages are
server-rendered routes backed by framework-light modules in `shared_code/modules/`.

## Public Routes

- `/producten` and `/pakketten`: catalogue overview pages for `single` and `package`
  products respectively. Components are excluded from both tabs. Each tab has its own
  filter and sort configuration; composition cannot be changed through a request filter.
- `/methodes`: redirects to the FAQ question that explains why packages replaced the
  method overview. The method overview template and its htmx endpoints remain in place.
- `/product/<gid>`: one publicly available product.
- `/methode/<gid>`: one publicly available method.
- `/compare/product/<gid>/<gid>/...`: compare two or more public products.
- `/compare/package/<gid>/<gid>/...`: compare public packages separately from single
  products. Each comparison route excludes products of the other compositions.
- `/compare/methode/<gid>/<gid>/...`: compare two or more public methods.

Detail routes return a styled 404 when the requested item does not exist or is not
publicly available. Comparison routes require at least two valid UUIDs of one entity
kind. Duplicate identifiers are ignored while preserving the original URL order;
items that are no longer public are omitted and reported to the visitor.

Packages retain the existing `/product/<gid>` detail pages and product favorite
identity. Method data, derivation, detail pages and comparisons remain available.
There is no redirect from `/methodes` to `/pakketten`; it points to the FAQ instead.

## Data Flow

`apps/_default/controllers/default.py` delegates catalogue access to the product,
method, vision, and comparison modules exposed by the shared backend. Those modules
construct public payloads only: importer-only fields and unavailable records do not
reach the page.

Detail pages render the item's public fields, supplier, education visions, and products
belonging to its method. The comparison template renders common properties and education visions in a matrix, with
a client-side option to show only differing rows.

Administrators can show or hide the complete **Inzichten** section on product and
method detail pages via **Catalogusinstellingen > Algemene instellingen > De 12 thema's**
(`/admin/catalog-settings`). The boolean setting is stored as `catalog.show_themes`
in `catalogus_setting` and read on each detail request. Themes are shown by default
when the key is absent; no migration or seeded row is needed. Hiding the section
preserves all vision data and leaves specifications and other detail-page actions available.

## Similar Learning Materials

At the bottom of a detail page, `SimilarMaterials` selects other public catalogue items:

- Methods must share at least one subject and have a public product.
- Products must share at least one subject and at least one level.
- The current item and removed items are excluded.

Each shared subject or level adds two ranking points. Sharing the supplier adds one,
so supplier preference can never outweigh an additional subject or level match.
Ties use the catalogue search's daily seeded random ordering. Results are cached for
five minutes, with the source's matching fields, day, and configured limit in the key.
The section is omitted when no relevant alternatives exist, including when the source
lacks the required subject or level data.

Administrators set the global maximum in the shared **Catalogusinstellingen > Algemene
instellingen** page (`/admin/catalog-settings`), under **Soortgelijke leermiddelen**. It is stored in the reusable
`catalogus_setting` table under the key `catalog.similar_material_limit`, defaults
to `9`, and accepts positive whole numbers only.
The same value applies to product and method pages for every visitor.
The setting is read on each request, and the current value is part of the suggestion
cache key, so a saved change takes effect immediately without restarting the application.
The `create_catalogus_setting_20261005_001` migration creates and seeds the setting.

`CatalogusSetting` extends `BaseTable`, providing the standard `gid`, `created_at`,
and `updated_at` fields alongside a unique `key` and JSONB `value`. The shared
`CatalogusSettings` module reads values with caller-provided defaults and allows
administrators and services to save JSON values. Individual features define their
own defaults and validation. Updating a setting preserves its GID and creation time.

Suggestions emit `catalog_search` events with `search_type="similar"`, source GID,
configured limit, result revisions, and scores, including on cache hits. Suggestion
links carry `source=similar`; the destination's `catalog_detail` event records this
attribution and the HTTP `Referer` when supplied by the browser.

Successful searches emit applog events with result row IDs and search scores. Those scores are
the relevance ranks described in [Search ranking](search-ranking.md). Detail
views and comparisons log the resolved effective-dated record and vision identifiers
used for their response.

## Related Docs

- [Catalogue participation](catalogue-participation.md): supplier status import, live counts, and the HTMX widget contract.
- [Catalogue filtering](catalog-filters.md): overview-page filter definitions and request handling.
- [Search ranking](search-ranking.md): relevance weights behind free-text catalogue search.
- [Payload type generation](../development/tooling.md#payload-type-generation): generated public payload types.
- [Applog](../integrations/applog.md): catalogue event payloads and audit processing.
