# Caching

`shared_code/services/caching/` caches the result of a slow block of code and
records which entities that result was built from, so an entry can be dropped
when one of them changes.

## Backends

`CACHE_BACKEND` is a comma-separated list of backends, fastest first. Unset
means `none`; `docker-compose.yml` defaults it to `redis`.

| Name       | Store                                                                                                         | Use                                                     |
| ---------- | ------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| `redis`    | `REDIS_CACHE_HOST`/`PORT`, logical database `REDIS_CACHE_DB` (default `1`, clear of py4web's sessions on `0`) | deployments                                             |
| `postgres` | `cache_entry` + `cache_dependency` tables                                                                     | second in a chain; survives a Redis outage              |
| `memory`   | this process only                                                                                             | tests and local development; not shared between workers |
| `none`     | nothing                                                                                                       | caching off, without any call site knowing              |

The `postgres` tables only exist if `CACHE_BACKEND` named `postgres` when
`migrate` ran. See [conditional migrations](../development/migrations.md#environment-dependent-migrations)
before adding it to a running installation.

A single name uses that backend directly. Several are wrapped in a
`ChainedCacheService`:

- **Reads** return the first member's hit, unless a later member misses. That
  later miss means the entry was invalidated there while the earlier member was
  unreachable, so the chain reports a miss rather than serve stale data.
  Unreachable members are skipped.
- **Writes** go to every member, so a later member can answer when an earlier
  one is down.
- **No backfill.** A hit in a later member isn't copied forward: `load_entry`
  returns the payload without its dependencies, and an entry stored without them
  could never be invalidated.

A failing backend never raises into the caller. The failure is logged as a
warning, a read becomes a miss and a write is dropped. A failed invalidation is
lost too, so that entry stays until its ttl runs out.

## Using it

Declare `caching: CacheService` on a module or service and endow injects the
backend `CACHE_BACKEND` names. A call site opens a block:

```python
with self.caching("catalog_filter_options", entity_kind, scope=None, ttl=300) as cache:
    if cache.valid:
        return cache.value
    return cache.set(expensive_query())
```

Run the queries inside the block: only queries that run there are recorded as
dependencies.

- **`name`** identifies the call site. Positional arguments vary the key and, if
  they are `TypedTable` or `TypedRows`, seed the dependency set.
- **`scope`** is keyword-only with no default, so a call site cannot widen its
  audience by leaving it out. Pass the actor for per-user results, a string for a
  role or tenant, or `None` for public data. An anonymous actor collapses onto
  the public scope.
- **`ttl`** in seconds or as a `timedelta`; `None` never expires on its own.
- **`lock=True`** makes concurrent misses on one key wait (up to 30 seconds) for
  the first to fill it, then re-read, instead of all running the query. Redis
  supports it and `memory` locks within one process; on `postgres` and `none`
  the block runs unlocked. A chain locks in the first member that supports it.
- **`cache.set(value)`** is the only write path. Returning without calling it
  caches nothing, which is how one branch of a call site opts out.

Values are serialized with `dill`. Anything able to write to the cache keyspace
can therefore execute code on read: the store must be as trusted as the app.

## Keys

`sha256(build id | name | scope | args...)`. Sets and mappings are sorted before
hashing; lists keep their order.

The build id is `SCHEMA_VERSION`: a hash of every file under `shared_code/`,
recomputed by `edwh setup`. After a `shared_code` change and `edwh setup`, no
entry from before is read again. A change elsewhere (a py4web template, a
controller), or a deploy that skips `edwh setup`, keeps the old build id and
keeps serving old entries. If such a change alters what a cached value looks
like, rename the call site's `name` or flush the cache with `invalidate_all()`.

## Dependencies and invalidation

While a block runs uncached, `DependencyRecorder` hooks TypeDAL's
`_after_execute` and `_after_collect` and walks every result set already in
memory:

- every uuid column becomes a `GidDep`, which spans all effective-dated versions
  of an entity and the tables that carry it as a foreign column;
- every `*.id` column becomes a `RowDep`, for tables that mutate in place;
- queried tables become `TableDep` dependencies even when the result is empty.
  Records passed into a block seed table+gid dependencies instead.

Over-tracking is deliberate: an extra dependency only costs an invalidation that
wasn't strictly needed.

`invalidate(gid)` drops every entry that recorded that gid; `invalidate_all()`
drops everything.

`invalidate_table(table, gid=gid)` drops that entity and table queries, including
empty queries; omitting `gid` clears the table. `invalidate_table_many(table, gids)`
batches affected entities. Effective-dated tables and model views share a name.

`define_tables` binds public write callbacks to `db.caching` for every business
model, excluding internals and cache storage. Inserts invalidate queries and the
gid; updates/deletes collect gids beforehand and invalidate in bulk. Models
without gids clear the table. Rebuilds, refreshes and raw SQL use
`invalidate_cache(db, table, ...)`. `cache.update_deps(*deps)` covers reads outside
a block and aggregate/external reads the recorder cannot observe.

Redis/memory invalidate before commit; PostgreSQL deletion shares the write
transaction. TODO: prevent stale refills across writes/commits. Catalogue TTLs
remain bounded at 300 seconds; do not cache uncommitted data.

The hooks are plain lists on a shared `db`, which is only safe because bjoern
serves one request per process at a time. Revisit if py4web gains threads or
anything here starts using TypeDAL's async workers.

## Finding what to cache

The admin page **Logs → Cache-kandidaten** (`/admin/logs/cache-candidates`) ranks
one day's routes by `(requests - distinct request shapes) * mean seconds`, the
time a cache that never missed twice on the same shape would have saved. A slow
route whose every request differs can't be helped by a cache and ranks low.

A request's shape is its route, its sorted query string and, when logged in, the
user. A per-user route therefore has about as many shapes as active users.

The counters come from the `route_stats` fixture, which runs first in `common()`
and `admin()` and splits each request into handler, template render and fixture
overhead. Routes that use neither aren't measured. `ROUTE_STATS` chooses where
measurements go:

| Value             | Effect                                                                                  |
| ----------------- | --------------------------------------------------------------------------------------- |
| `none` (or unset) | nothing recorded; the timing fixtures stay out of the request path                      |
| `redis`           | the counters behind the admin page (30-day retention)                                   |
| `applog`          | one `slow_request` event per request slower than `ROUTE_STATS_SLOW_MS` (default 500 ms) |
| `redis,applog`    | both                                                                                    |

Only `redis` can feed the admin page: ranking needs every request counted and a
distinct count over request shapes, and neither survives a threshold. The page
and its tile on `/admin/logs` hide unless `redis` is in the chain. `edwh setup`
defaults to `redis` in development and `applog` elsewhere. For the event's
fields, see [Applog](../integrations/applog.md#slow-requests).

## Current call sites

- Catalogue filter options, per entity kind, public, 300s. See
  [Catalogue filtering](catalog-filters.md#option-caching).

`FlagBasedCache` (`py4web/common/fixtures/flag_based_cache.py`) and TypeDAL's
`builder.cache(ttl=...)` are separate, older mechanisms and don't go through this
service.
