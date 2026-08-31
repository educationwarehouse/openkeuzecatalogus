"""Shared supplier import helpers used by admin interfaces."""

import json
import typing as t
import uuid

from pgskewer.helpers import queue_job

from shared_code.data_model.tables import ImporterRun, ImporterRunCountStat, ImporterRunErrorStat, Supplier
from shared_code.util.strings import pluralize


class SupplierImportPollContext(t.TypedDict):
    """Template context for the supplier import poll partial."""

    job_key: str
    status: str
    status_message: str
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

    label: str
    metrics: list[ImportMetricValue]


class SerializedImporterRun(t.TypedDict):
    """Template-friendly representation of one importer run."""

    gid: str
    started_at: str
    finished_at: str
    duration_ms: int
    success: bool
    status: RunStatus
    failure_message: str | None
    warnings: list[dict[str, str]]
    count_groups: list[ImportCountGroup]
    error_groups: list[ImportErrorGroup]


class SupplierRunsContext(t.TypedDict):
    """Template context for the supplier importer-run overview page."""

    supplier: Supplier
    run_count: int
    recent_imports_label: str | None
    runs: list[SerializedImporterRun]


def can_start_import(supplier: Supplier) -> bool:
    """Return whether a supplier row is configured for Edu-V imports."""
    return bool(supplier.endpoint_type != "none" and supplier.endpoint_base_url)


def start_import_for_supplier(supplier: Supplier) -> str:
    """Start an Edu-V import through the backend hook and return the job key."""
    db = Supplier._db
    assert db, "can't continue without a db"

    job_key = str(uuid.uuid7())
    queue_job(
        db,
        f"start_importer_{supplier.endpoint_type}",
        payload={
            "supplier_gid": str(supplier.gid),
            "base_url": supplier.endpoint_base_url,
            "endpoint_publisher": supplier.endpoint_publisher,
            "endpoint_type": supplier.endpoint_type,
            # not passed directly via pgq for some reason:
            "job_key": job_key,
        },
        dill=True,
        unique_key=job_key,
    )
    return job_key


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
            "supplier_gid": str(supplier.gid),
            "supplier_name": str(supplier.name or supplier.gid),
            "poll_url": poll_url,
            "job_key": job_key,
            "result_pretty": format_job_result(result_json),
        }

    pending = db.executesql(
        """
        SELECT status
        FROM pgqueuer
        WHERE dedupe_key = %(job_key)s
        LIMIT 1;
        """,
        placeholders={"job_key": job_key},
    )
    pending_status = pending[0][0] if pending else None
    return {
        "status": "pending",
        "status_message": "Wachten in de wachtrij..." if pending_status == "queued" else "Importeren...",
        "supplier_gid": str(supplier.gid),
        "supplier_name": str(supplier.name or supplier.gid),
        "poll_url": poll_url,
        "job_key": job_key,
        "result_pretty": None,
    }


def build_supplier_runs_context(supplier: Supplier, job_key: str | None = None) -> SupplierRunsContext:
    """Build the supplier importer-run overview page context."""
    query = ImporterRun.supplier_gid == supplier.gid
    if job_key:
        query &= ImporterRun.job_key == job_key

    runs = ImporterRun.where(query).select(orderby=~ImporterRun.started_at).collect()
    return {
        "supplier": supplier,
        "run_count": len(runs),
        "recent_imports_label": None if job_key else pluralize("recente import", len(runs), "recente imports"),
        "runs": [serialize_run(run) for run in runs],
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


def serialize_run(run: ImporterRun) -> SerializedImporterRun:
    """Convert one importer run into a template-friendly structure."""
    count_rows = (
        ImporterRunCountStat.where(ImporterRunCountStat.run_gid == run.gid)
        .select(
            orderby=(
                ImporterRunCountStat.count_type,
                ImporterRunCountStat.count_label,
                ImporterRunCountStat.count_key,
                ImporterRunCountStat.metric,
            )
        )
        .collect()
    )

    count_field = ImporterRunErrorStat.id.count()
    error_code_field = ImporterRunErrorStat.error_code
    error_rows = (
        ImporterRunErrorStat.where(ImporterRunErrorStat.run_gid == run.gid)
        .select(
            error_code_field,
            count_field,
            groupby=error_code_field,
            orderby=(~count_field, error_code_field),
        )
        .execute()
    )
    error_groups: list[ImportErrorGroup] = [
        ImportErrorGroup(
            error_code=str(row[error_code_field]),
            count=int(row[count_field]),
        )
        for row in error_rows
    ]
    warnings = [warning for warning in (run.warnings_json or []) if isinstance(warning, dict)]
    status = run_status(success=bool(run.success), error_groups=error_groups, warnings=warnings)

    return {
        "gid": str(run.gid),
        "started_at": run.started_at.strftime("%Y-%m-%d %H:%M:%S") if run.started_at else "",
        "finished_at": run.finished_at.strftime("%Y-%m-%d %H:%M:%S") if run.finished_at else "",
        "duration_ms": int(run.duration_ms or 0),
        "success": bool(run.success),
        "status": status,
        "failure_message": str(run.failure_message) if run.failure_message else None,
        "warnings": warnings,
        "count_groups": group_count_rows(count_rows),
        "error_groups": error_groups,
    }


def run_status(success: bool, error_groups: list[ImportErrorGroup], warnings: list[dict[str, str]]) -> RunStatus:
    """Resolve the display status for one importer run."""
    if not success:
        return {"label": "Mislukt", "badge_class": "text-bg-danger"}
    elif error_groups or warnings:
        return {"label": "Onvolledig", "badge_class": "text-bg-warning"}
    else:
        return {"label": "Succes", "badge_class": "text-bg-success"}


def group_count_rows(rows: t.Iterable[ImporterRunCountStat]) -> list[ImportCountGroup]:
    """Group stored count stats by subject for display."""
    groups: dict[str, ImportCountGroup] = {}
    order: list[str] = []
    for row in rows:
        group_key = f"{row.count_type}:{row.count_key}"
        if group_key not in groups:
            groups[group_key] = ImportCountGroup(label=str(row.count_label or row.count_key), metrics=[])
            order.append(group_key)
        groups[group_key]["metrics"].append(
            ImportMetricValue(
                label=metric_label(str(row.metric)),
                value=int(row.value or 0),
            )
        )
    return [groups[group_key] for group_key in order]


def metric_label(metric: str) -> str:
    """Translate stored metric keys to a readable label."""
    return {
        "seen": "Gezien",
        "new": "Nieuw",
        "changed": "Gewijzigd",
        "skipped": "Overgeslagen",
        "removed": "Verwijderd",
        "issues": "Issues",
        "imported": "Geimporteerd",
        "attempted": "Geprobeerd",
        "uploaded": "Geüpload",
        "failed": "Mislukt",
        "product_count": "Producten nu",
        "method_count": "Methodes nu",
    }.get(metric, metric.replace("_", " "))
