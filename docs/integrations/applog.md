# Applog Integration

## Overview

Application events are captured through `shared_code.services.applog.Applogger`.

Current flow:
1. Application code logs events (`Applogger.log_auth_action(...)` or `fire(...)`).
2. Events are serialized into a local disk-backed deque (`DequeApplogger`) by default.
3. `pgq-applog` runs a scheduled job every minute to process deque entries.
4. Processed signals/evidence are persisted to database tables (`signal`, `evidence`).

## Implementations

`Applogger.from_env()` selects implementation via `APPLOG_FAKE`:
- `APPLOG_FAKE=0` (default): `DequeApplogger` (queue-first async processing).
- `APPLOG_FAKE=1`: `FileApplogger` (append-only JSONL at configured path).

## Environment Variables

- `APPLOG_FAKE` (`1`/`0`) selects file logger vs deque logger.
- `APPLOG_DEQUE_DIR` (default: `/shared_applog`) storage directory for queued signals.
- `APPLOG_PATH` (default: `/shared_applog/events.jsonl`) file target for `FileApplogger`.

## Queue Consumer

The applog queue consumer lives in `pgq/consumers/applog.py`:
- Schedule: `process_applog_deque_every_minute` (`* * * * *`)
- Worker function: `process_applog_deque(db, batch_size=50, ...)`, with the PGQ job's database context passed in by the consumer.

Batch behavior:
- Reads up to `batch_size` records from deque.
- Parses event payloads.
- Persists rows through `process_applog_signal(...)`.
- Returns processed count (`0` when empty).

## Auth Events

`py4web` auth actions are logged through `LoggingAuthForms` / `AppAuth`:
- login / invalid login attempts
- logout
- register / verify_email / password flows from auth post-processing

Captured fields include action, user/email context, success flag, IP, user agent, and timestamp.

## Catalogue Events

Public catalogue activity is logged through dedicated helpers:

- `log_catalog_search(...)`: resolved filters, normalized search terms, pagination,
  result IDs, and search scores (the relevance ranks from
  [search ranking](../architecture/search-ranking.md))
- `log_catalog_detail(...)`: requested GID, resolved effective-dated row ID, and
  resolved vision row IDs, plus the HTTP `Referer` when available. Visits through
  suggestion links also carry `search_type="similar"`.
- `log_catalog_compare(...)`: requested GIDs, resolved row IDs, and resolved vision
  row IDs

Detail-page alternatives use `log_catalog_search(...)` with `search_type="similar"`.
These events include `source_gid`, `suggestion_limit`, result revisions, and overlap
scores in `result_scores`. They have no dynamic filter, sort, or search-weight revisions:
their ranking is based on shared subjects and levels, followed by supplier preference.
Cached suggestion displays are logged too, with `cache_hit=true`.

`catalog_search_report_v1` exposes `search_type`, `source_gid`, and
`suggestion_limit`. Historical events without a search type default to `catalog`;
recommendation impressions use `similar`, including empty lists. Search analytics
should filter on `search_type = 'catalog'` to exclude recommendation impressions.

`log_catalog_search(...)` writes the applied catalogue-setting revision IDs to
the event's `details` object. They identify the exact effective-dated revision,
rather than only the stable GID, so historical search results remain
interpretable after a setting changes:

- `dynamic_sort_ed_id`: the applied `dynamic_sort_ed.id`.
- `active_filter_ed_ids`: a mapping from filter slug to its
  `dynamic_filter_ed.id`.
- `search_rank_weight_ed_ids`: the `search_rank_weight_ed.id` values used for
  the searched entity type.

## Slow Requests

With `applog` in the `ROUTE_STATS` chain, every request slower than
`ROUTE_STATS_SLOW_MS` (in milliseconds; default `500`, floored at `50`) writes
one event with `kind="event"` and `action="slow_request"`. This covers routes
built with `common()` or `admin()`; others aren't measured. The sink is
`ApplogRouteStats` in `py4web/common/models/backend/route_stats.py`. In the
[audit viewer](#admin-audit-viewer), filter on action `slow_request`.

`details` holds:

- `day`, `route`, `params` (the query string, sorted, values as strings);
- `anonymous`: whether the visitor was logged out;
- `total_ms`: server time from the first fixture to the response, excluding
  network and queueing; split into `controller_ms` (handler body),
  `template_ms` (render) and `overhead_ms` (session, auth, database connect and
  commit);
- `threshold_ms`: the threshold in force when the event was written, so events
  from before a threshold change can be told apart.

The event names no actor: `user_gid` stays empty and the actor id isn't in
`details`. `session_gid` is still set, as `try_fire` fills it for every event.

Ranking routes as cache candidates needs the `redis` sink instead; see
[Caching](../architecture/caching.md#finding-what-to-cache).

## Admin Audit Viewer

Service identities such as `service:admin.cli_support` are stored in
`signal.service_actor`; `signal.user_gid` stays a UUID or NULL. Apply migration
`add_signal_service_actor_20261105_001` before running the updated consumers. The
viewer uses the service actor as its fallback label when no user is present.

The queue consumer commits each event independently. A failed event is rolled
back and moved to `<APPLOG_DEQUE_DIR>/failed` for inspection, without blocking
later events. Invalid JSON payloads are also moved there. Failures produce an
ERROR log record. The failed queue is not retried automatically: inspect and
replay payloads after correcting their cause. A crash after a database commit
but before the queue transaction completes can result in duplicate signals.

Decision-process mutations log their action, actor and affected process/record
identifiers without duplicating submitted prose. CLI role grants and revocations
already use `AuthContext` audit hooks; user deletion also records its actor,
subject and removed memberships.

Admins can inspect the 500 most recent persisted signals at `/admin/logs/audit`. The
read-only grid supports pagination and filters for session, user, event, source, and
action. Signal details include the full linked evidence payload when present.

User links use both direct signal fields and explicitly logged user associations in
the evidence payload. The viewer does not modify or delete audit data.
