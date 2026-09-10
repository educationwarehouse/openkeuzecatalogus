# Public Catalogue Pages

The public catalogue is served by `py4web/apps/_default`. Its overview pages use
HTMX endpoints for filtering and results, while detail and comparison pages are
server-rendered routes backed by framework-light modules in `shared_code/modules/`.

## Public Routes

- `/producten` and `/methodes`: catalogue overview pages.
- `/product/<gid>`: one publicly available product.
- `/methode/<gid>`: one publicly available method.
- `/compare/product/<gid>/<gid>/...`: compare two or more public products.
- `/compare/methode/<gid>/<gid>/...`: compare two or more public methods.

Detail routes return a styled 404 when the requested item does not exist or is not
publicly available. Comparison routes require at least two valid UUIDs of one entity
kind. Duplicate identifiers are ignored while preserving the original URL order;
items that are no longer public are omitted and reported to the visitor.

## Data Flow

`apps/_default/controllers/default.py` delegates catalogue access to the product,
method, vision, and comparison modules exposed by the shared backend. Those modules
construct public payloads only: importer-only fields and unavailable records do not
reach the page.

The detail template currently renders the public payload as formatted JSON. The
comparison template renders common properties and education visions in a matrix, with
a client-side option to show only differing rows.

Successful searches emit applog events with result row IDs and search scores. Those scores are
the relevance ranks described in [Search ranking](search-ranking.md). Detail
views and comparisons log the resolved effective-dated record and vision identifiers
used for their response.

## Related Docs

- [Catalogue filtering](catalog-filters.md): overview-page filter definitions and request handling.
- [Search ranking](search-ranking.md): relevance weights behind free-text catalogue search.
- [Payload type generation](../development/tooling.md#payload-type-generation): generated public payload types.
- [Applog](../integrations/applog.md): catalogue event payloads and audit processing.
