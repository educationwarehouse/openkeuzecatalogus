"""Kennisnet-specific import queries used by admin interfaces."""

import typing as t
import uuid

from pgskewer.helpers import queue_job
from typedal import TypeDAL

from shared_code.data_model.tables import (
    KENNISNET_COVERAGE_STATUS_LABELS,
    ImporterRun,
    ImporterRunEvent,
    KennisnetCoverageStatus,
)
from shared_code.modules.scrapers.admin_imports import (
    KennisnetCoverageGroup,
    KennisnetImportPollContext,
    KennisnetSupplierOutcome,
    KennisnetValidationErrorGroup,
    SerializedImporterRun,
    _serialize_kennisnet_import_run,
    _validation_error_groups,
    finished_importer_runs,
    metric_label,
    serialize_run,
)


def start_kennisnet_import(db: TypeDAL) -> str:
    """Queue one import that refreshes every configured Kennisnet supplier."""
    job_key = str(uuid.uuid7())
    queue_job(
        db,
        "start_importer_edu-v-kennisnet",
        payload={"job_key": job_key, "trigger": "manual"},
        dill=True,
        unique_key=job_key,
    )
    return job_key


def build_kennisnet_import_poll_context(db: TypeDAL, job_key: str, poll_url: str) -> KennisnetImportPollContext:
    """Return the current queue state for one manually started Kennisnet import."""
    result = db.executesql(
        """
        SELECT status
            FROM pgqueuer_result
            WHERE unique_key = %(job_key)s
            LIMIT 1;
        """,
        placeholders={"job_key": job_key},
    )
    if result:
        job_status = str(result[0][0])
        return {
            "status": "success" if job_status == "successful" else "failure",
            "status_message": "Import voltooid" if job_status == "successful" else "Import mislukt",
            "pgqueuer_status": job_status,
            "job_key": job_key,
            "poll_url": poll_url,
            "progress": None,
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
    if not pending:
        return {
            "status": "failure",
            "status_message": "Import is uit de wachtrij verwijderd",
            "pgqueuer_status": "missing",
            "job_key": job_key,
            "poll_url": poll_url,
            "progress": None,
        }

    pending_status = str(pending[0][0])
    return {
        "status": "pending",
        "status_message": "Wachten in de wachtrij..." if pending_status == "queued" else "Importeren...",
        "pgqueuer_status": pending_status,
        "job_key": job_key,
        "poll_url": poll_url,
        "progress": kennisnet_import_progress(job_key),
    }


def kennisnet_import_progress(job_key: str) -> dict[str, int] | None:
    """Return the current Kennisnet image-upload progress snapshot."""
    run = ImporterRun.where((ImporterRun.job_key == job_key) & (ImporterRun.phase == "images")).first()
    if not run:
        return None
    event = ImporterRunEvent.where(
        (ImporterRunEvent.run_gid == run.gid)
        & (ImporterRunEvent.event_type == "progress")
        & (ImporterRunEvent.metric == "live")
    ).first()
    if not event or not event.details:
        return None
    return t.cast(dict[str, int], event.details | {"image_suppliers_completed": int(event.value or 0)})


def list_kennisnet_import_history_runs() -> list[SerializedImporterRun]:
    """Return the retained aggregate Kennisnet imports, newest first."""
    runs = (
        finished_importer_runs()
        .where(source="edu-v-kennisnet-import")
        .join("warnings")
        .select(orderby=~ImporterRun.started_at)
        .collect()
    )

    if not runs:
        return []

    error_run_gids = set(
        ImporterRunEvent.where(ImporterRunEvent.run_gid.belongs(runs.column("gid")))
        .where(event_type="error")
        .column(ImporterRunEvent.run_gid, groupby=ImporterRunEvent.run_gid)
    )
    return [serialize_run(run, has_errors=run.gid in error_run_gids) for run in runs]


def kennisnet_import_coverage(run_gid: str) -> list[KennisnetCoverageGroup]:
    """Group the persisted Kennisnet publisher snapshot by coverage state."""
    publisher_observations = ImporterRunEvent.where(
        (ImporterRunEvent.run_gid == run_gid) & (ImporterRunEvent.event_type == "observation")
    ).orderby(ImporterRunEvent.entity_name)

    return [
        KennisnetCoverageGroup(
            label=KENNISNET_COVERAGE_STATUS_LABELS[status],
            publishers=[
                observation.details or {}
                for observation in publisher_observations
                if (observation.details or {}).get("coverage_status") == status
            ],
        )
        for status in KennisnetCoverageStatus
    ]


def _add_supplier_outcome_examples(
    run_gid: str, supplier_gid: str | None, outcomes: dict[str, KennisnetSupplierOutcome]
) -> None:
    """Attach persisted entity examples to the collected supplier counters."""
    entity_query = (ImporterRunEvent.run_gid == run_gid) & (ImporterRunEvent.event_type == "entity")
    if supplier_gid:
        entity_query &= ImporterRunEvent.supplier_gid == supplier_gid
    entity_events = ImporterRunEvent.where(entity_query).orderby(
        ImporterRunEvent.supplier_gid, ImporterRunEvent.entity_type, ImporterRunEvent.metric, ImporterRunEvent.id
    )
    for entity_event in entity_events:
        if not entity_event.supplier_gid:
            continue
        outcome = outcomes.get(entity_event.supplier_gid)
        if not outcome:
            continue
        target = outcome["method_examples"] if entity_event.entity_type == "method" else outcome["product_examples"]
        target.setdefault(metric_label(entity_event.metric), []).append(
            {
                "name": str(entity_event.entity_name or entity_event.entity_gid or "Onbekend"),
                "olid": str(entity_event.entity_olid or ""),
            },
        )


def kennisnet_import_supplier_outcomes(
    run_gid: str,
    supplier_gid: str | None = None,
    include_examples: bool = True,
) -> dict[str, KennisnetSupplierOutcome]:
    """Collect persisted method and product changes by selected supplier."""
    count_query = (
        (ImporterRunEvent.run_gid == run_gid)
        & (ImporterRunEvent.event_type == "metric")
        & (ImporterRunEvent.scope_type == "supplier_change")
    )
    if supplier_gid:
        count_query &= ImporterRunEvent.supplier_gid == supplier_gid

    count_stats = ImporterRunEvent.where(count_query).orderby(
        ImporterRunEvent.supplier_name, ImporterRunEvent.scope_key, ImporterRunEvent.metric
    )

    outcomes: dict[str, KennisnetSupplierOutcome] = {}
    for count_stat in count_stats:
        if not count_stat.supplier_gid:
            continue
        outcome_supplier_gid = count_stat.supplier_gid
        outcome = outcomes.setdefault(
            outcome_supplier_gid,
            KennisnetSupplierOutcome(
                supplier_gid=outcome_supplier_gid,
                supplier_name=count_stat.supplier_name or outcome_supplier_gid,
                methods={},
                products={},
                method_examples={},
                product_examples={},
            ),
        )
        target = outcome["methods"] if count_stat.scope_key.endswith(":method") else outcome["products"]
        target[metric_label(count_stat.metric)] = int(count_stat.value)

    if not include_examples:
        return outcomes

    _add_supplier_outcome_examples(run_gid, supplier_gid, outcomes)
    return outcomes


def kennisnet_import_validation_errors(
    run_gid: str,
    supplier_gid: str | None = None,
) -> list[KennisnetValidationErrorGroup]:
    """Collect persisted source-row validation errors, grouped by supplier."""
    query = (
        (ImporterRunEvent.run_gid == run_gid)
        & (ImporterRunEvent.event_type == "error")
        & (ImporterRunEvent.metric == "row_validation_failed")
    )
    if supplier_gid:
        query &= ImporterRunEvent.supplier_gid == supplier_gid
    error_rows = ImporterRunEvent.where(query).orderby(ImporterRunEvent.supplier_name, ImporterRunEvent.id)
    return _validation_error_groups(error_rows)


def _get_kennisnet_import_run(
    extras: tuple[str, ...] | None = None,
    **query_args: str,
) -> SerializedImporterRun | None:
    run = finished_importer_runs().where(query_args).where(source="edu-v-kennisnet-import").first()

    return _serialize_kennisnet_import_run(run, extras=extras) if run else None


def get_kennisnet_import_run(
    run_gid: str,
    extras: tuple[str, ...] | None = None,
) -> SerializedImporterRun | None:
    """Load one retained aggregate Kennisnet import by its public identifier."""
    return _get_kennisnet_import_run(gid=run_gid, extras=extras)


def kennisnet_import_run_exists(run_gid: str) -> bool:
    """Return whether an aggregate Kennisnet import is available for viewing."""
    return finished_importer_runs(gid=run_gid).where(source="edu-v-kennisnet-import").exists()


def get_kennisnet_import_run_by_job_key(
    job_key: str,
    extras: tuple[str, ...] | None = None,
) -> SerializedImporterRun | None:
    """Load a completed aggregate Kennisnet import by its queue key."""
    return _get_kennisnet_import_run(job_key=job_key, extras=extras)
