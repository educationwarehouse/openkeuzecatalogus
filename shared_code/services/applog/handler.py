"""Helpers for persisting applog signals and deque batches."""

import datetime as dt
import hashlib
import json
import typing as t
from uuid import UUID

from typedal import TypeDAL

from shared_code.data_model import Evidence, Signal
from shared_code.modules.auth import AuthAdapter
from shared_code.services.applog.contracts import ApplogEvent, Applogger, ApplogSignal
from shared_code.services.applog.deque import DequeApplogger
from shared_code.util.lists import batch_deque


class AuditLogStats(t.TypedDict):
    """Aggregate applog counters for the admin logs overview."""

    total: int
    last_24h: int
    admin_actions: int


def save_applog_evidence(session: str | UUID | None, source: ApplogEvent) -> Evidence:
    """Store evidence once per payload hash and return the corresponding row."""
    # bereken de hash_value van de json payload.
    # EDIT DEZE JSON NIET, DIE MOET GESORTEERD ZIJN OM DUPLICATEN TE VOORKOMEN
    json_data = json.dumps(source).encode("utf-8")
    hash_value = hashlib.sha1(json_data).hexdigest()  # noqa: S324 only used to deduplicate; not for secrets hashing
    # zoek bestaand bewijs
    evidence = Evidence(sha1_digest=hash_value)
    if not evidence:
        # als geen bestaand bewijs, maak nieuw bewijs
        evidence = Evidence.insert(session_gid=session, source=source, sha1_digest=hash_value)

    return evidence


def audit_log_stats() -> AuditLogStats:
    """Return aggregate applog counters for the admin logs overview."""
    total = Signal.count()
    last_24h = Signal.where(Signal.ts >= (dt.datetime.now() - dt.timedelta(days=1))).count()
    admin_actions = Signal.where(name="admin-action").count()
    return {
        "total": total,
        "last_24h": last_24h,
        "admin_actions": admin_actions,
    }


def process_applog_signal(
    db: TypeDAL,
    name: str,
    signal_source: str,
    evidence: ApplogEvent | None = None,
    session_gid: str | UUID | None = None,
    user_gid: str | UUID | None = None,
    ts: dt.datetime | str | None = None,
    related: str | UUID | None = None,
) -> Signal:
    """Persist a single applog signal row, optionally linked to evidence."""
    signal_fields: dict[str, t.Any] = {
        "name": name,
        "source": signal_source,
        # uses db.signal instead of Signal to prevent typing issues with default() not being callable:
        "ts": ts if ts else db.signal.ts.default(),
        "user_gid": user_gid,
        "session_gid": session_gid,
        "related": related,
    }
    if evidence is not None:
        evidence_row = save_applog_evidence(session_gid, evidence)
        # maak nieuw signaal verwijzend naar bestaand of nieuw bewijs
        signal_fields.update(
            {
                "evidence_id": evidence_row.id,
                "evidence_gid": evidence_row.gid,
            }
        )
    else:
        if session_gid is not None:
            raise ValueError("Session_gid was provided, but no evidence was provided. Session data will be lost.")

    return Signal.insert(**signal_fields)


def process_applog_buffer(db: TypeDAL, events: list[ApplogSignal]) -> None:
    """Persist buffered applog events using the caller-owned database context."""
    successful_signals = 0
    failed_signals = []
    for event in events:
        if not event:
            continue

        try:
            short_related = str(related)[:8] if (related := event.get("related")) else None

            print("[applog] {signal_source}/{name} ({short_related}...)".format(**event, short_related=short_related))
            process_applog_signal(
                db,
                name=event["name"],
                signal_source=event["signal_source"],
                evidence=event.get("evidence"),
                session_gid=event.get("session_gid"),
                user_gid=event.get("user_gid"),
                ts=event.get("ts"),
                related=event.get("related"),
            )
            successful_signals += 1
        except Exception as e:
            db.rollback()
            # waarschijnlijk invalide data
            print("[applog] invalid data:", event, e)
            failed_signals.append(event)

    print(f"[applog] successful: {successful_signals}, failed: {failed_signals!r}")


def process_applog_deque(db: TypeDAL, batch_size: int = 50, applog: Applogger | None = None) -> int:
    """Process queued applog signals with the caller-owned database context."""
    applog = applog or DequeApplogger.with_injected(
        db=db,
        auth_adapter=AuthAdapter.for_service("pgq.process_applog_deque"),
    )

    if not isinstance(applog, DequeApplogger):
        return -1

    deque = applog.deque

    buffer: list[ApplogSignal] = []
    for raw_event in batch_deque(deque, batch_size):
        event_or_events = json.loads(raw_event)
        events = [event_or_events] if isinstance(event_or_events, dict) else event_or_events
        buffer.extend(events)

    if not buffer:
        return 0

    process_applog_buffer(db, buffer)
    return len(buffer)
