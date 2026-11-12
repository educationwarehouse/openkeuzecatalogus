# Mail Integration

## Overview

Mail delivery is handled via `shared_code.services.mail.Mailer`.

Runtime behavior:

- `Mailer.send(..., blocking=False)` (default) enqueues a `send_email_message` PGQ job and returns immediately.
- `Mailer.send(..., blocking=True)` sends directly in-process.

Queue processing:

- PGQ consumer entrypoint: `send_email_message` in `pgq/consumers/maintenance.py`.
- The maintenance consumer opens a dedicated backend context and calls
  `backend.mailer.send_email_message(...)`.

## Transport Selection

`Mailer.from_env()` chooses implementation via `SMTP_FAKE`:

- `SMTP_FAKE=1`: `MockMailer` (writes JSONL messages for tests/dev).
- `SMTP_FAKE=0`: `SMTPMailer` (real SMTP transport).

## Environment Variables

Core:

- `SMTP_FAKE` (`1` or `0`) selects fake vs real transport.
- `DEFAULT_FROM_ADDRESS` default sender used by app flows.

Fake mailer:

- `SMTP_FAKE_INBOX_PATH` (default: `/shared_cache/mail/mock_inbox.jsonl`).

SMTP mailer:

- `SMTP_SERVER` (host or `host:port`)
- `SMTP_PORT` (used when not included in `SMTP_SERVER`, default `587`)
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_SENDER` (optional explicit sender; falls back to `SMTP_USER`)
- `SMTP_TLS` (`1`/`0`)
- `SMTP_SSL` (`1`/`0`)

If required SMTP settings are incomplete, `SMTPMailer.from_env(...)` raises `OSError("Incomplete SMTP Config")`.

## Auth Integration

Py4web auth uses this mailer:

- `auth.sender = backend.mailer` in `py4web/common/models/backend/auth_cls.py`.
- Registration email confirmation and password reset emails flow through the same contract.
