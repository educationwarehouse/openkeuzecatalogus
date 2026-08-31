"""Helpers for persisting applog signals and deque batches."""

import contextlib
import datetime as dt
import hashlib
import json
import typing as t
from uuid import UUID

from typedal import TypeDAL
from typedal.types import Row

from shared_code.services.applog.contracts import ApplogEvent, Applogger, ApplogSignal
from shared_code.services.applog.deque import DequeApplogger
from shared_code.util.email import normalize_email_for_lookup


class AuditLogRow(t.TypedDict):
    """Normalized applog row for admin audit-log rendering."""

    id: int
    ts: dt.datetime
    name: str
    source: str
    session_gid: str | None
    user_gid: str | None
    user: str | None
    related: str | None
    evidence: ApplogEvent | None


class AuditLogStats(t.TypedDict):
    """Aggregate applog counters for the admin logs overview."""

    total: int
    last_24h: int
    admin_actions: int


def save_applog_evidence(db: TypeDAL, session: str | UUID | None, source: ApplogEvent) -> Row:
    """Store evidence once per payload hash and return the corresponding row."""
    # bereken de hash_value van de json payload.
    # EDIT DEZE JSON NIET, DIE MOET GESORTEERD ZIJN OM DUPLICATEN TE VOORKOMEN
    json_data = json.dumps(source).encode("utf-8")
    hash_value = hashlib.sha1(json_data).hexdigest()  # noqa: S324 only used to deduplicate; not for secrets hashing
    # zoek bestaand bewijs
    evidence = db(db.evidence.sha1_digest == hash_value).select(limitby=(1, 1)).first()
    if not evidence:
        # als geen bestaand bewijs, maak nieuw bewijs
        new_evidence_id = db.evidence.insert(session_gid=session, source=source, sha1_digest=hash_value)
        evidence = db.evidence[new_evidence_id]

    return evidence


def all_audit_logs(db: TypeDAL, limit: int = 500) -> list[AuditLogRow]:
    """Return recent applog rows with their evidence payload when present."""
    rows = db(db.signal.id > 0).select(
        db.signal.id,
        db.signal.ts,
        db.signal.name,
        db.signal.source,
        db.signal.session_gid,
        db.signal.user_gid,
        db.signal.related,
        db.evidence.source,
        left=db.evidence.on(db.evidence.id == db.signal.evidence_id),
        orderby=~db.signal.ts,
        limitby=(0, limit),
    )

    logs: list[AuditLogRow] = []
    for row in rows:
        evidence = row.evidence.source if row.evidence else None
        evidence_user = None
        if isinstance(evidence, dict):
            evidence_user = evidence.get("admin_email") or evidence.get("email") or evidence.get("by_eddie_email")

        logs.append(
            {
                "id": row.signal.id,
                "ts": row.signal.ts,
                "name": row.signal.name,
                "source": row.signal.source,
                "session_gid": row.signal.session_gid,
                "user_gid": row.signal.user_gid,
                "user": evidence_user or row.signal.user_gid,
                "related": row.signal.related,
                "evidence": evidence,
            }
        )

    return logs


def user_audit_logs(
    db: TypeDAL,
    *,
    user_gid: str | UUID,
    user_email: str | None,
    limit: int = 500,
    scan_limit: int = 5000,
) -> list[AuditLogRow]:
    """Return recent applog rows tied to one user by gid, related gid, or auth email."""
    gid = str(user_gid)
    normalized_email = normalize_email_for_lookup(user_email)

    rows = db(db.signal.id > 0).select(
        db.signal.id,
        db.signal.ts,
        db.signal.name,
        db.signal.source,
        db.signal.session_gid,
        db.signal.user_gid,
        db.signal.related,
        db.evidence.source,
        left=db.evidence.on(db.evidence.id == db.signal.evidence_id),
        orderby=~db.signal.ts,
        limitby=(0, max(scan_limit, limit)),
    )

    logs: list[AuditLogRow] = []
    for row in rows:
        evidence = row.evidence.source if row.evidence else None
        evidence_user = None
        evidence_gid = None
        evidence_email = ""
        detail_gid_matches_user = False
        detail_email_matches_user = False

        if isinstance(evidence, dict):
            evidence_user = evidence.get("admin_email") or evidence.get("email") or evidence.get("by_eddie_email")
            evidence_gid = evidence.get("user_gid")
            evidence_email = normalize_email_for_lookup(str(evidence.get("email") or ""))

            details = evidence.get("details")
            if isinstance(details, dict):
                detail_gid_matches_user = any(
                    str(details.get(key) or "") == gid
                    for key in ("target_user_gid", "subject_gid", "user_gid", "related_gid")
                )
                detail_email_matches_user = any(
                    normalize_email_for_lookup(str(details.get(key) or "")) == normalized_email
                    for key in ("candidate_email", "target_email", "email")
                )

        if not (
            str(row.signal.user_gid or "") == gid
            or str(row.signal.related or "") == gid
            or str(evidence_gid or "") == gid
            or (bool(normalized_email) and evidence_email == normalized_email)
            or detail_gid_matches_user
            or (bool(normalized_email) and detail_email_matches_user)
        ):
            continue

        logs.append(
            {
                "id": row.signal.id,
                "ts": row.signal.ts,
                "name": row.signal.name,
                "source": row.signal.source,
                "session_gid": row.signal.session_gid,
                "user_gid": row.signal.user_gid,
                "user": evidence_user or row.signal.user_gid,
                "related": row.signal.related,
                "evidence": evidence,
            }
        )

        if len(logs) >= limit:
            break

    return logs


def audit_log_stats(db: TypeDAL) -> AuditLogStats:
    """Return aggregate applog counters for the admin logs overview."""
    total = db(db.signal.id > 0).count()
    last_24h = db(db.signal.ts >= (dt.datetime.now() - dt.timedelta(days=1))).count()
    admin_actions = db(db.signal.name == "admin-action").count()
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


def process_applog_buffer(db: TypeDAL, events: list[ApplogSignal]) -> None:
    """Persist buffered applog events using the caller-owned database context."""
    successful_signals = 0
    failed_signals = []
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


def process_applog_deque(db: TypeDAL, batch_size: int = 50, applog: Applogger | None = None) -> int:
    """Process queued applog signals with the caller-owned database context."""
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

    process_applog_buffer(db, buffer)
    return len(buffer)
