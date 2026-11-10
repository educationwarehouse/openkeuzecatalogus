"""Helpers for persisting applog signals and deque batches."""

import datetime as dt
import hashlib
import json
import logging
import typing as t
from pathlib import Path
from uuid import UUID

from diskcache import Deque
from typedal import TypeDAL

from shared_code.data_model import AnyDict, Evidence, Signal
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
    # only used to deduplicate; not for secrets hashing
    hash_value = hashlib.sha1(json_data, usedforsecurity=False).hexdigest()
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
    service_actor = None
    if isinstance(user_gid, str) and user_gid.startswith("service:"):
        service_actor = user_gid
        user_gid = None
    signal_fields: AnyDict = {
        "name": name,
        "source": signal_source,
        # uses db.signal instead of Signal to prevent typing issues with default() not being callable:
        "ts": ts if ts else Signal.ts.default(),  # ty: ignore[call-non-callable]
        "user_gid": user_gid,
        "service_actor": service_actor,
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


def process_applog_buffer(db: TypeDAL, events: list[ApplogSignal]) -> list[ApplogSignal]:
    """Commit events independently and return failed payloads for inspection."""
    failures = []

    for event in events:
        try:
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
            db.commit()
        except Exception:
            db.rollback()
            logging.exception("Audit event could not be persisted; moving it to the failed queue")
            failures.append(event)

    return failures


def process_applog_deque(db: TypeDAL, batch_size: int = 50, applog: Applogger | None = None) -> int:
    """Persist events and set aside failures without blocking later events."""
    applog = applog or DequeApplogger.with_injected(
        db=db,
        auth_adapter=AuthAdapter.for_service("pgq.process_applog_deque"),
    )

    if not isinstance(applog, DequeApplogger):
        return -1

    deque = applog.deque

    failed_queue = Deque(directory=str(Path(deque.directory) / "failed"))
    with deque.transact(), failed_queue.transact():
        buffer: list[ApplogSignal] = []
        for raw_event in batch_deque(deque, batch_size):
            try:
                event_or_events = json.loads(raw_event)
            except ValueError, TypeError:
                logging.exception("Invalid audit JSON; moving the raw payload to the failed queue")
                failed_queue.append(raw_event)
                continue

            if isinstance(event_or_events, dict):
                events = [event_or_events]
            elif isinstance(event_or_events, list):
                events = event_or_events
            else:
                logging.error("Invalid audit payload type; moving the raw payload to the failed queue")
                failed_queue.append(raw_event)
                continue

            buffer.extend(events)

        if not buffer:
            return 0

        failures = process_applog_buffer(db, buffer)
        for event in failures:
            failed_queue.append(json.dumps(event, default=str))

    logging.info("Audit events persisted: %s; failed: %s", len(buffer) - len(failures), len(failures))
    return len(buffer)
