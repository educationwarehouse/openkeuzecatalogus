# Error Signals

Stored error tickets call `ErrorSignalService.send(signal)` after their TOML file is written. The default non-blocking call persists the signal in diskcache; `send(signal, blocking=True)` delivers it through the configured backend immediately.

`ERROR_SIGNAL_BACKEND` selects the delivery implementation:

- `mock`: writes one JSONL payload per signal to `ERROR_SIGNAL_MOCK_PATH` (default `/shared_cache/error_signals/mock.jsonl`).
- `ntfy`: publishes one notification per processed batch to `NTFY_ERROR_URL`. Its click target opens the admin error overview filtered to that batch's ticket IDs.

Pending payloads are stored in the disk-backed queue at `ERROR_SIGNAL_QUEUE_PATH`
(default `/shared_cache/error_signals/pending`). The `pgq-applog` consumer processes
them every minute through its `process_ticket_signal_queue_every_minute` schedule.
Backends implement `send_one` and can override `send_batch`; ntfy uses the latter to
avoid one notification per ticket.

Delivery failures are printed with an `[error-signal]` prefix. They do not create another error ticket or enqueue another signal.

Future backends such as `odoo` can implement `ErrorSignalService` and be selected through `ERROR_SIGNAL_BACKEND`.
