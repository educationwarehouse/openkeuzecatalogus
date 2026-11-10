"""Shared supplier import helpers used by admin interfaces."""

import json
import typing as t
import uuid
from collections import Counter

from more_itertools import flatten
from pgskewer.helpers import queue_job
from typedal import QueryBuilder, TypeDAL

from shared_code.data_model import AnyDict
from shared_code.data_model.tables import (
    ImporterRun,
    ImporterRunEvent,
    Supplier,
)
from shared_code.modules.scrapers.kennisnet_import import KENNISNET_IMPORTER_TYPES
from shared_code.util.strings import pluralize

Unset = t.NewType("Unset", object)

UNSET_SENTINEL = Unset({})


class SupplierImportPollContext(t.TypedDict):
    """Template context for the supplier import poll partial."""

    job_key: str
    status: str
    status_message: str
    pgqueuer_status: str
    supplier_gid: str
    supplier_name: str
    poll_url: str
    result_pretty: str | None


class RunStatus(t.TypedDict):
    """Display status metadata for one importer run."""

    label: str
    badge_class: str


class ImportErrorGroup(t.TypedDict, total=False):
    """Aggregated error-count row for one importer run."""

    error_code: str
    count: int


class ImportMetricValue(t.TypedDict):
    """One labeled metric value within a count group."""

    label: str
    value: int


class ImportCountGroup(t.TypedDict):
    """Grouped count stats for one subject in the importer run view."""

    count_type: str
    count_key: str
    label: str
    metrics: list[ImportMetricValue]


class KennisnetValidationError(t.TypedDict):
    """One rejected product row for an import result."""

    row_index: int
    messages: list[str]
    source_row: str | None


class KennisnetValidationErrorGroup(t.TypedDict):
    """Rejected product rows grouped by supplier."""

    supplier_gid: str
    supplier_name: str
    errors: list[KennisnetValidationError]


class SerializedImporterRun(t.TypedDict):
    """Template-friendly representation of one importer run."""

    gid: str
    started_at: str
    finished_at: str
    duration_ms: int
    duration_label: str
    trigger: str | None
    success: bool
    status: RunStatus
    failure_message: str | None
    warnings: list[dict[str, object]]
    count_groups: list[ImportCountGroup]
    error_groups: list[ImportErrorGroup]
    validation_errors: list[KennisnetValidationError]


class SupplierRunsContext(t.TypedDict):
    """Template context for the supplier importer-run overview page."""

    supplier: Supplier
    run_count: int
    recent_imports_label: str | None
    runs: list[SerializedImporterRun]


class KennisnetImportPollContext(t.TypedDict):
    """Template context for one queued Kennisnet batch import."""

    status: str
    status_message: str
    pgqueuer_status: str
    job_key: str
    poll_url: str
    progress: dict[str, int] | None


class KennisnetCoverageGroup(t.TypedDict):
    """One coverage category with its observed Kennisnet publishers."""

    label: str
    publishers: list[dict[str, object]]


class KennisnetSupplierOutcome(t.TypedDict):
    """Method and product change counters for one imported supplier."""

    supplier_gid: str
    supplier_name: str
    methods: dict[str, int]
    products: dict[str, int]
    method_examples: dict[str, list[dict[str, str]]]
    product_examples: dict[str, list[dict[str, str]]]


def can_start_import(supplier: Supplier) -> bool:
    """Return whether a supplier row is configured for Edu-V imports."""
    if supplier.endpoint_type in KENNISNET_IMPORTER_TYPES:
        return bool(str(supplier.endpoint_publisher or "").strip())
    return bool(supplier.endpoint_type != "none" and supplier.endpoint_base_url)


def start_import_for_supplier(db: TypeDAL, supplier: Supplier) -> str:
    """Start an Edu-V import through the backend hook and return the job key."""
    job_key = str(uuid.uuid7())
    queue_job(
        db,
        f"start_importer_{supplier.endpoint_type}",
        payload={
            "supplier_gid": supplier.gid,
            "base_url": supplier.endpoint_base_url,
            "endpoint_publisher": supplier.endpoint_publisher,
            "endpoint_uses_pagination": supplier.endpoint_uses_pagination,
            "endpoint_type": supplier.endpoint_type,
            # not passed directly via pgq for some reason:
            "job_key": job_key,
        },
        dill=True,
        unique_key=job_key,
    )
    return job_key


def finished_importer_runs(
    gid: str | Unset | None = UNSET_SENTINEL,
    supplier_gid: str | Unset | None = UNSET_SENTINEL,
) -> QueryBuilder[ImporterRun]:
    """Return importer runs that reached a terminal phase."""
    query = ImporterRun.where(ImporterRun.phase.belongs(("completed", "failed")))
    if gid is not UNSET_SENTINEL:
        query = query.where(gid=gid)
    if supplier_gid is not UNSET_SENTINEL:
        query = query.where(supplier_gid=supplier_gid)
    return query


def _validation_error_groups(error_rows: t.Iterable[ImporterRunEvent]) -> list[KennisnetValidationErrorGroup]:
    """Group preloaded source-row validation errors by supplier."""
    groups: dict[str, KennisnetValidationErrorGroup] = {}
    for error_row in error_rows:
        details = t.cast(AnyDict, (error_row.details or {}).get("error_details") or {})
        row_index = details.get("row_index")
        messages = details.get("messages")
        if (
            not isinstance(row_index, int)
            or not isinstance(messages, list)
            or not all(isinstance(message, str) for message in messages)
        ):
            continue
        source_row = details.get("source_row")

        supplier_name = error_row.supplier_name or "Onbekende leverancier"
        supplier_gid = error_row.supplier_gid or supplier_name
        group = groups.setdefault(
            supplier_gid,
            KennisnetValidationErrorGroup(
                supplier_gid=supplier_gid,
                supplier_name=supplier_name,
                errors=[],
            ),
        )
        group["errors"].append(
            KennisnetValidationError(
                row_index=row_index,
                messages=messages,
                source_row=json.dumps(source_row, ensure_ascii=False, indent=2)
                if isinstance(source_row, dict)
                else None,
            )
        )

    for group in groups.values():
        group["errors"].sort(key=lambda error: error["row_index"])
    return list(groups.values())


def importer_count_rows(*run_gids: str) -> dict[str, list[ImporterRunEvent]]:
    """Load metric events grouped by importer run identifier."""
    rows = (
        ImporterRunEvent.where(ImporterRunEvent.run_gid.belongs(run_gids))
        .where(event_type="metric")
        .select(
            ImporterRunEvent.run_gid,
            ImporterRunEvent.scope_type,
            ImporterRunEvent.scope_key,
            ImporterRunEvent.scope_label,
            ImporterRunEvent.metric,
            ImporterRunEvent.value,
            orderby=(
                ImporterRunEvent.run_gid,
                ImporterRunEvent.scope_type,
                ImporterRunEvent.scope_label,
                ImporterRunEvent.scope_key,
                ImporterRunEvent.metric,
            ),
        )
        .collect()
    )
    return rows.group_by_value("run_gid")


def importer_error_rows(*run_gids: str) -> dict[str, list[ImporterRunEvent]]:
    """Load error events grouped by importer run identifier."""
    if not run_gids:
        return {}

    rows = (
        ImporterRunEvent.where(ImporterRunEvent.run_gid.belongs(run_gids))
        .where(event_type="error")
        .select(ImporterRunEvent.run_gid, ImporterRunEvent.metric)
        .collect()
    )
    return rows.group_by_value("run_gid")


def importer_validation_errors(*run_gids: str) -> dict[str, list[KennisnetValidationError]]:
    """Load row-validation errors grouped by importer run identifier."""
    rows = (
        ImporterRunEvent.where(ImporterRunEvent.run_gid.belongs(run_gids))
        .where(event_type="error")
        .where(metric="row_validation_failed")
        .select(
            ImporterRunEvent.run_gid,
            ImporterRunEvent.supplier_gid,
            ImporterRunEvent.supplier_name,
            ImporterRunEvent.details,
            orderby=(ImporterRunEvent.run_gid, ImporterRunEvent.supplier_name, ImporterRunEvent.id),
        )
        .collect()
    )
    return {
        run_gid: list(flatten(group["errors"] for group in _validation_error_groups(error_rows)))
        for run_gid, error_rows in rows.group_by_value("run_gid").items()
    }


def _serialize_kennisnet_import_run(
    run: ImporterRun,
    extras: tuple[str, ...] | None = None,
) -> SerializedImporterRun:
    """Load reporting facts for one aggregate Kennisnet import."""
    return _serialize_kennisnet_import_runs(run, extras=extras)[run.gid]


def _serialize_kennisnet_import_runs(
    *runs: ImporterRun, extras: tuple[str, ...] | None = None
) -> dict[str, SerializedImporterRun]:
    if not runs:
        return {}
    run_gids = [_.gid for _ in runs]

    default_extras = ("counts", "errors", "validation")
    extras = default_extras if extras is None else extras

    count_rows_by_run = importer_count_rows(*run_gids) if "counts" in extras else {}
    error_rows_by_run = importer_error_rows(*run_gids) if "errors" in extras else {}
    validation_errors_by_run = importer_validation_errors(*run_gids) if "validation" in extras else {}
    runs_with_warnings = ImporterRun.where(ImporterRun.gid.belongs(run_gids)).join("warnings").collect()
    return {
        run.gid: serialize_run(
            run,
            count_rows=count_rows_by_run.get(run.gid, []),
            error_rows=error_rows_by_run.get(run.gid, []),
            validation_errors=validation_errors_by_run.get(run.gid, []),
        )
        for run in runs_with_warnings
    }


def build_supplier_import_poll_context(supplier: Supplier, job_key: str, poll_url: str) -> SupplierImportPollContext:
    """Build a small template context for the OL-style supplier import poll."""
    db = Supplier._db
    assert db, "can't continue without a db"

    result = db.executesql(
        """
        SELECT status, result
            FROM pgqueuer_result
            WHERE unique_key = %(job_key)s
            LIMIT 1;
        """,
        placeholders={"job_key": job_key},
    )
    if result:
        job_status, result_json = result[0]
        return {
            "status": "success" if job_status == "successful" else "failure",
            "status_message": "Import voltooid" if job_status == "successful" else "Import mislukt",
            "pgqueuer_status": str(job_status),
            "supplier_gid": supplier.gid,
            "supplier_name": str(supplier.name or supplier.gid),
            "poll_url": poll_url,
            "job_key": job_key,
            "result_pretty": format_job_result(result_json),
        }

    # TODO(PR157 #15): read result and queue status atomically to avoid reporting completion as missing.
    pending = db.executesql(
        """
        SELECT status
            FROM pgqueuer
            WHERE dedupe_key = %(job_key)s
            LIMIT 1;
        """,
        placeholders={"job_key": job_key},
    )
    if not pending:
        return {
            "status": "failure",
            "status_message": "Import is uit de wachtrij verwijderd",
            "pgqueuer_status": "missing",
            "supplier_gid": supplier.gid,
            "supplier_name": str(supplier.name or supplier.gid),
            "poll_url": poll_url,
            "job_key": job_key,
            "result_pretty": None,
        }

    pending_status = str(pending[0][0])
    return {
        "status": "pending",
        "status_message": "Wachten in de wachtrij..." if pending_status == "queued" else "Importeren...",
        "pgqueuer_status": pending_status,
        "supplier_gid": supplier.gid,
        "supplier_name": str(supplier.name or supplier.gid),
        "poll_url": poll_url,
        "job_key": job_key,
        "result_pretty": None,
    }


def build_supplier_runs_context(supplier: Supplier, job_key: str | None = None) -> SupplierRunsContext:
    """Build the supplier importer-run overview page context."""
    # TODO(PR157 #19): bound/lazy-load validation details rather than rendering every retained source row.
    query = finished_importer_runs(supplier_gid=supplier.gid)
    if job_key:
        query = query.where(job_key=job_key)

    runs = query.select(orderby=~ImporterRun.started_at).collect()
    serialized_by_gid = _serialize_kennisnet_import_runs(*runs)
    serialized_runs = [serialized_by_gid[run.gid] for run in runs]

    return {
        "supplier": supplier,
        "run_count": len(serialized_runs),
        "recent_imports_label": (
            None if job_key else pluralize("recente import", len(serialized_runs), plural="recente imports")
        ),
        "runs": serialized_runs,
    }


def format_job_result(result_json: object) -> str | None:
    """Pretty-print the queued job result for the success view."""
    if result_json in (None, "", {}):
        return None
    try:
        parsed = json.loads(result_json) if isinstance(result_json, str) else result_json
    except TypeError, ValueError:
        parsed = result_json
    if isinstance(parsed, dict | list):
        return json.dumps(parsed, indent=2, sort_keys=True)
    return str(parsed)


def build_import_error_groups(error_counts: dict[str, int]) -> list[ImportErrorGroup]:
    """Convert error counts into sorted template rows."""
    error_groups = [
        ImportErrorGroup(error_code=error_code, count=count)
        for error_code, count in sorted(error_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return error_groups


def count_import_errors(error_rows: t.Iterable[ImporterRunEvent]) -> dict[str, int]:
    """Count error events by their metric code."""
    return dict(Counter(error_event.metric for error_event in error_rows))


def serialize_run(
    run: ImporterRun,
    count_rows: t.Iterable[ImporterRunEvent] = (),
    error_rows: t.Iterable[ImporterRunEvent] = (),
    validation_errors: t.Iterable[KennisnetValidationError] = (),
    has_errors: bool = False,
) -> SerializedImporterRun:
    """Convert preloaded importer-run facts into a template-friendly structure."""
    # List readers preload the warning relationship to avoid queries in this loop.
    duration_ms = int(run.duration_ms or 0)

    error_counts = count_import_errors(error_rows)
    error_groups = build_import_error_groups(error_counts)

    warnings = run.warnings_json

    status = run_status(
        success=run.success,
        error_groups=error_groups,
        warnings=warnings,
        has_errors=has_errors,
    )

    trigger = run.payload_json.get("trigger") if run.payload_json else None
    if not isinstance(trigger, str):
        trigger = None

    return SerializedImporterRun(
        gid=run.gid,
        started_at=run.started_at.strftime("%Y-%m-%d %H:%M:%S") if run.started_at else "",
        finished_at=run.finished_at.strftime("%Y-%m-%d %H:%M:%S") if run.finished_at else "",
        duration_ms=duration_ms,
        duration_label=format_duration(duration_ms),
        trigger=trigger,
        success=run.success,
        status=status,
        failure_message=run.failure_message if run.failure_message else None,
        warnings=warnings,
        count_groups=group_count_rows(count_rows),
        error_groups=error_groups,
        validation_errors=list(validation_errors),
    )


def format_duration(duration_ms: int) -> str:
    """Format a recorded duration for the importer-run interfaces."""
    total_seconds = duration_ms // 1_000
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} uur {minutes} min {seconds} sec"
    elif minutes:
        return f"{minutes} min {seconds} sec"
    else:
        return f"{seconds} sec"


def run_status(
    success: bool,
    error_groups: list[ImportErrorGroup],
    warnings: list[dict[str, object]],
    has_errors: bool = False,
    has_warnings: bool = False,
) -> RunStatus:
    """Resolve the display status for one importer run."""
    if not success:
        return {"label": "Mislukt", "badge_class": "text-bg-danger"}
    elif has_errors or error_groups or has_warnings or warnings:
        return {"label": "Onvolledig", "badge_class": "text-bg-warning"}
    else:
        return {"label": "Succes", "badge_class": "text-bg-success"}


def group_count_rows(rows: t.Iterable[ImporterRunEvent]) -> list[ImportCountGroup]:
    """Group stored count stats by subject for display."""
    groups: dict[str, ImportCountGroup] = {}
    order: list[str] = []
    for row in rows:
        group_key = f"{row.scope_type}:{row.scope_key}"
        if group_key not in groups:
            groups[group_key] = ImportCountGroup(
                count_type=row.scope_type,
                count_key=row.scope_key,
                label=row.scope_label or row.scope_key,
                metrics=[],
            )
            order.append(group_key)
        groups[group_key]["metrics"].append(
            ImportMetricValue(
                label=metric_label(row.metric),
                value=int(row.value or 0),
            ),
        )
    return [groups[group_key] for group_key in order]


def metric_label(metric: str) -> str:
    """Translate stored metric keys to a readable label."""
    return {
        "seen": "Gezien",
        "new": "Nieuw",
        "changed": "Gewijzigd",
        "unchanged": "Ongewijzigd",
        "skipped": "Overgeslagen",
        "removed": "Verwijderd",
        "issues": "Fouten",
        "invalid": "Fouten",
        "imported": "Geimporteerd",
        "attempted": "Geprobeerd",
        "uploaded": "Geüpload",
        "failed": "Mislukt",
        "known": "Bekend bij Kennisnet",
        "configured": "Geconfigureerd",
        "matched": "Komt voor in catalogus",
        "product_count": "Producten nu",
        "method_count": "Methodes nu",
    }.get(metric, metric.replace("_", " "))
