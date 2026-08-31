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
