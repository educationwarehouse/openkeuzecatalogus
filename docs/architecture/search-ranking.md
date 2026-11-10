# Search Ranking

Free-text catalogue search for products and methods is relevance-ranked.
The weights that decide the ordering live in the database, not in code, and are editable by admins.

## Two Search Implementations

Both live in `shared_code/data_model/mixins/search.py`.

- `SearchMixin`: legacy ranking by field order. The position of a field in `search_fields`
  determines its rank; there is nothing to configure. Used by `AuthUser`, `Supplier`,
  `Vision`, and `Organisation`.
- `RankedSearchMixin`: weighted ranking driven by the `search_rank_weight` table.
  Used by `Product` and `Method`.

`apply_search()` is the shared entrypoint and delegates to `_apply_search()`, which the ranked
mixin overrides. Every caller therefore gets the ranked behaviour automatically for products and
methods: the public catalogue's `q` filter, the admin grids, and the relevance preview all use
the same code path.

## Where the Weights Live

The `search_rank_weight` table stores one row per ranking rule:

- `entity_kind`: `product` or `method`.
- `key`: stable identifier for the rule, unique per `entity_kind`. It names the rule but does not
  select behaviour; the matching is driven by `source_field` and the related-record columns.
- `section` and `sort_order`: grouping and ordering in the admin editor only.
- `label`: what the rule matches on, shown to the admin.
- `source_field`: the field the search term is compared against.
- `foreign_key`, `related_table`, `related_key`: set together to score a match on a *related*
  record. The rule then matches rows whose `foreign_key` points at a related row where
  `source_field` matches, for example a product matching on its supplier's name.
- `exact`, `prefix`, `contains`, `trigram`: the scores, `0`-`5000` or empty.

A score of `NULL` is not the same as `0`. An empty score removes that condition entirely, so it
neither scores nor *finds* the row. A score of `0` keeps the row findable but awards no points.

## Scoring Model

For every include term in the query:

1. Each rule builds its conditions: `exact` (case-insensitive full match), `prefix`
   (`value%`), `contains` (substring), and `trigram` (PostgreSQL `similarity()` above the
   threshold, skipped for terms containing a space).
2. A rule awards only its *strongest* matching condition, as a `CASE ... ELSE 0 END`, so a
   name that matches exactly does not additionally collect its prefix and contains points.
3. Rule scores are summed across all rules and all include terms.

The total is selected as the extra field `search_rank` and used as the primary `ORDER BY`,
descending, ahead of any ordering the caller already applied.

Query parsing (`parsed_search_terms`) is shell-like: terms are split on whitespace, quoted
phrases stay together, and a leading `-` marks an exclude term. Exclude terms filter rows out and
never contribute to the score.

Trigram matching requires the `pg_trgm` extension, enabled both at database init
(`postgres/extensions.sql`) and by migration `enable_pg_trgm_and_unaccent_20060000_001`. The similarity
threshold is a fixed `0.30` in `direct_search_rank_rule()` and is **not** configurable through the
admin page.

## Global Admin Search

The administrator-only global search, available at `admin/search` and through its navigation
search control (`Ctrl/Cmd+K`), uses the shared `SearchMixin` matching behaviour rather than the
configurable catalogue-ranking rules above. It searches fixed admin tiles, the Logs cards, and Kennisnet
catalogue tabs by title or an explicit alias such as `users` for Gebruikersbeheer. Screen results reuse
their labels, icons, and destinations in the preview and full search page. It also searches boards, schools, locations,
teaching teams, suppliers, methods, products, and visions, then links each row to its relevant admin grid.

Product, method, and supplier search models have GIN trigram indexes on `name` and `olid` for
this search. The other entity types remain in scope and use their normal configured search fields.

## Admin Page

`apps/admin` exposes an editor under `search-relevance/<entity_kind>` where an admin edits the
four scores per rule and previews the effect. The preview passes the submitted values as transient
`score_overrides` into the same ranked search, so the top results and their scores can be checked
before anything is saved. Only admins and services may save; saving validates every score before
committing, and rejects the whole submission on the first invalid value.

Rules themselves (which fields are matched, and which related records are followed) are not
editable in the admin page, only their scores. The trigram threshold is not editable either.

## Reporting Loop

Catalogue searches log their result identifiers together with the computed `search_rank` per row.
Those scores end up in the `catalog_search_report_v1` materialized view as `result_scores`, which
makes the effect of a weight change measurable against real queries.

## Related Docs

- [Catalogue filtering](catalog-filters.md): the `q` filter that feeds this search.
- [Public catalogue pages](public-catalogue.md): where catalogue search runs.
- [Applog](../integrations/applog.md): the logged search events and scores.
