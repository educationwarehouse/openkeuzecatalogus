"""Helpers for persisting applog signals and deque batches."""

import contextlib
import datetime as dt
import hashlib
import json
import typing as t
from uuid import UUID

from typedal import TypeDAL
from typedal.types import Row

from shared_code.services.applog import DequeApplogger
from shared_code.services.applog.contracts import ApplogEvent, Applogger, ApplogSignal
from shared_code.services.database import database_context


def save_applog_evidence(db: TypeDAL, session: str | UUID | None, source: ApplogEvent) -> Row:
    """Store evidence once per payload hash and return the corresponding row."""
    # bereken de hash_value van de json payload.
    # EDIT DEZE JSON NIET, DIE MOET GESORTEERD ZIJN OM DUPLICATEN TE VOORKOMEN
    hash_value = hashlib.sha1(json.dumps(source).encode("utf-8")).hexdigest()
    # zoek bestaand bewijs
    evidence = db(db.evidence.sha1_digest == hash_value).select(limitby=(1, 1)).first()
    if not evidence:
        # als geen bestaand bewijs, maak nieuw bewijs
        new_evidence_id = db.evidence.insert(session_gid=session, source=source, sha1_digest=hash_value)
        evidence = db.evidence[new_evidence_id]

    return evidence


def process_applog_signal(
    db: TypeDAL,
    name: str,
    signal_source: str,
    evidence: ApplogEvent | None = None,
    session_gid: str | UUID | None = None,
    user_gid: str | UUID | None = None,
    ts: dt.datetime | str | None = None,
    related: str | UUID | None = None,
) -> None:
    """Persist a single applog signal row, optionally linked to evidence."""
    signal_fields: dict[str, t.Any] = {
        "name": name,
        "source": signal_source,
        "ts": ts if ts else db.signal.ts.default(),
        "user_gid": user_gid,
        "session_gid": session_gid,
        "related": related,
    }
    if evidence is not None:
        evidence_row = save_applog_evidence(db, session_gid, evidence)
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

    db.signal.insert(**signal_fields)


def process_applog_buffer(events: list[ApplogSignal]) -> None:
    """Processes all the received events from the events buffer using process_applog_signal."""
    successful_signals = 0
    failed_signals = []
    with database_context("celery.process_applog_buffer") as db:
        for event in events:
            if not event:
                continue

            try:
                short_related = str(related)[:8] if (related := event.get("related")) else None

                print("{signal_source}/{name} ({short_related}...)".format(**event, short_related=short_related))
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
                print("[stats]", "Incorrecte Data", event, e)
                failed_signals.append(event)

    print(f"Successful: {successful_signals}, failed: {failed_signals!r}")


def process_applog_deque(batch_size: int = 50, applog: Applogger | None = None) -> int:
    """Process up to `batch_size` queued applog signals from the configured deque."""
    applog = applog or DequeApplogger.from_env()
    if not isinstance(applog, DequeApplogger):
        return -1
    deque = applog.deque

    buffer: list[ApplogSignal] = []
    with contextlib.suppress(IndexError):
        while len(buffer) < batch_size:
            event_or_events = json.loads(deque.popleft())
            events = [event_or_events] if isinstance(event_or_events, dict) else event_or_events
            buffer.extend(events)

    if not buffer:
        return 0

    process_applog_buffer(buffer)
    return len(buffer)
