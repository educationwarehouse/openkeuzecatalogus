"""Tests for shared supplier-import admin helpers."""

import datetime as dt
import typing as t
import uuid

from pgskewer.helpers import queue_job
from typedal import TypeDAL

from shared_code.data_model import ImporterRun, ImporterRunEvent, Supplier
from shared_code.modules.scrapers.admin_imports import (
    build_supplier_runs_context,
    can_start_import,
    format_job_result,
    group_count_rows,
    importer_count_rows,
    importer_error_rows,
    metric_label,
    run_status,
    serialize_run,
)
from shared_code.modules.scrapers.kennisnet_import_results import (
    build_kennisnet_import_poll_context,
    get_kennisnet_import_run,
    get_kennisnet_import_run_by_job_key,
    kennisnet_import_coverage,
    kennisnet_import_progress,
    kennisnet_import_run_exists,
    kennisnet_import_supplier_outcomes,
    kennisnet_import_validation_errors,
    list_kennisnet_import_history_runs,
    start_kennisnet_import,
)


def _insert_importer_run(
    supplier: Supplier,
    *,
    job_key: str,
    success: bool = True,
    failure_message: str | None = None,
) -> ImporterRun:
    """Create one importer-run row for shared helper tests."""
    row = ImporterRun.insert(
        source="pytest",
        endpoint_type=str(supplier.endpoint_type or ""),
        supplier_gid=supplier.gid,
        supplier_name=supplier.name,
        job_key=job_key,
        started_at=dt.datetime(2026, 6, 25, 10, 0, 0),
        finished_at=dt.datetime(2026, 6, 25, 10, 1, 30),
        duration_ms=90000,
        success=success,
        failure_message=failure_message,
        payload_json={},
    )
    assert row is not None
    return row


def test_can_start_import_requires_configured_endpoint(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
) -> None:
    """Suppliers must have a non-none endpoint type and base URL to start imports."""
    assert migrated_db_per_file is None

    configured = supplier_factory(
        name="Configured Supplier",
        email_domains=["configured-import.example.test"],
        endpoint_type="edu-v",
    )
    configured.update_record(endpoint_base_url="https://example.test/api/")

    missing_url = supplier_factory(
        name="Missing URL Supplier",
        email_domains=["missing-url-import.example.test"],
        endpoint_type="edu-v",
    )
    missing_url.update_record(endpoint_base_url=None)

    kennisnet_configured = supplier_factory(
        name="Kennisnet Supplier",
        email_domains=["kennisnet-import.example.test"],
        endpoint_type="edu-v-kennisnet-v2",
    )
    kennisnet_configured.update_record(endpoint_publisher="Kennisnet Publisher", endpoint_base_url=None)

    kennisnet_missing_publisher = supplier_factory(
        name="Kennisnet Missing Publisher",
        email_domains=["kennisnet-missing-publisher.example.test"],
        endpoint_type="edu-v-kennisnet-v2",
    )
    kennisnet_missing_publisher.update_record(endpoint_publisher=None, endpoint_base_url=None)
    db_per_file.commit()

    assert can_start_import(configured)
    assert not can_start_import(missing_url)
    assert can_start_import(kennisnet_configured)
    assert not can_start_import(kennisnet_missing_publisher)


def test_format_job_result_formats_json_and_scalars() -> None:
    """Queued result payloads should render as readable text."""
    assert format_job_result(None) is None
    assert format_job_result("") is None
    assert format_job_result({}) is None
    assert format_job_result('{"seen": 2}') == '{\n  "seen": 2\n}'
    assert format_job_result({"seen": 2}) == '{\n  "seen": 2\n}'
    assert format_job_result(12) == "12"


def test_group_count_rows_and_metric_label_build_display_groups(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
) -> None:
    """Count stats should be grouped per subject with readable metric labels."""
    assert migrated_db_per_file is None

    supplier = supplier_factory(name="Grouped Supplier", email_domains=["grouped-import.example.test"])
    run = _insert_importer_run(supplier, job_key="grouped-job")
    ImporterRunEvent.insert(
        run_gid=run.gid,
        supplier_gid=supplier.gid,
        supplier_name=supplier.name,
        event_type="metric",
        scope_type="method",
        scope_key="method-1",
        scope_label="Method One",
        metric="seen",
        entity_type="metric",
        value=5,
    )
    ImporterRunEvent.insert(
        run_gid=run.gid,
        supplier_gid=supplier.gid,
        supplier_name=supplier.name,
        event_type="metric",
        scope_type="method",
        scope_key="method-1",
        scope_label="Method One",
        metric="changed",
        entity_type="metric",
        value=1,
    )
    ImporterRunEvent.insert(
        run_gid=run.gid,
        supplier_gid=supplier.gid,
        supplier_name=supplier.name,
        event_type="metric",
        scope_type="supplier",
        scope_key="supplier-1",
        scope_label="Supplier One",
        metric="product_count",
        entity_type="metric",
        value=9,
    )
    db_per_file.commit()

    rows = (
        ImporterRunEvent.where(ImporterRunEvent.run_gid == run.gid)
        .select(
            orderby=(
                ImporterRunEvent.scope_type,
                ImporterRunEvent.scope_label,
                ImporterRunEvent.scope_key,
                ImporterRunEvent.metric,
            )
        )
        .collect()
    )

    assert group_count_rows(rows) == [
        {
            "count_type": "method",
            "count_key": "method-1",
            "label": "Method One",
            "metrics": [
                {"label": "Gewijzigd", "value": 1},
                {"label": "Gezien", "value": 5},
            ],
        },
        {
            "count_type": "supplier",
            "count_key": "supplier-1",
            "label": "Supplier One",
            "metrics": [
                {"label": "Producten nu", "value": 9},
            ],
        },
    ]
    assert metric_label("custom_metric") == "custom metric"


def test_serialize_run_and_build_supplier_runs_context_include_stats(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
) -> None:
    """Run serialization should include grouped counts, error aggregates, and display status."""
    assert migrated_db_per_file is None

    supplier = supplier_factory(
        name="Run Supplier",
        email_domains=["run-import.example.test"],
        endpoint_type="edu-v",
    )
    run = _insert_importer_run(supplier, job_key="job-1", success=True)
    ImporterRunEvent.insert(
        run_gid=run.gid,
        supplier_gid=supplier.gid,
        supplier_name=supplier.name,
        event_type="metric",
        scope_type="method",
        scope_key="method-1",
        scope_label="Method One",
        metric="seen",
        entity_type="metric",
        value=5,
    )
    ImporterRunEvent.insert(
        run_gid=run.gid,
        supplier_gid=supplier.gid,
        supplier_name=supplier.name,
        event_type="metric",
        scope_type="method",
        scope_key="method-1",
        scope_label="Method One",
        metric="changed",
        entity_type="metric",
        value=2,
    )
    ImporterRunEvent.insert(
        run_gid=run.gid,
        supplier_gid=supplier.gid,
        supplier_name=supplier.name,
        entity_type="product",
        event_type="error",
        metric="missing-name",
    )
    ImporterRunEvent.insert(
        run_gid=run.gid,
        supplier_gid=supplier.gid,
        supplier_name=supplier.name,
        entity_type="product",
        event_type="error",
        metric="missing-name",
    )
    db_per_file.commit()

    serialized = serialize_run(
        run,
        count_rows=importer_count_rows(run.gid)[run.gid],
        error_rows=importer_error_rows(run.gid)[run.gid],
    )
    context = build_supplier_runs_context(supplier)

    assert serialized["status"] == {"label": "Onvolledig", "badge_class": "text-bg-warning"}
    assert serialized["count_groups"] == [
        {
            "count_type": "method",
            "count_key": "method-1",
            "label": "Method One",
            "metrics": [
                {"label": "Gewijzigd", "value": 2},
                {"label": "Gezien", "value": 5},
            ],
        }
    ]
    assert serialized["error_groups"] == [{"error_code": "missing-name", "count": 2}]
    assert context["run_count"] == 1
    assert context["recent_imports_label"] == "1 recente import"
    assert context["runs"] == [serialized]


def test_run_status_covers_failure_incomplete_and_success() -> None:
    """Run status labels should reflect failure and partial-error states."""
    assert run_status(success=False, error_groups=[], warnings=[]) == {
        "label": "Mislukt",
        "badge_class": "text-bg-danger",
    }
    assert run_status(success=True, error_groups=[{"error_code": "x", "count": 1}], warnings=[]) == {
        "label": "Onvolledig",
        "badge_class": "text-bg-warning",
    }
    assert run_status(success=True, error_groups=[], warnings=[]) == {
        "label": "Succes",
        "badge_class": "text-bg-success",
    }


def test_kennisnet_import_supplier_outcomes_groups_counts_and_examples(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
) -> None:
    """Kennisnet outcomes should retain only attributed supplier changes and examples."""
    assert migrated_db_per_file is None

    supplier = supplier_factory(name="Outcome Supplier", email_domains=["outcomes.example.test"])
    run = _insert_importer_run(supplier, job_key="kennisnet-outcomes")
    unknown_supplier_gid = str(uuid.uuid4())
    ImporterRunEvent.insert(
        run_gid=run.gid,
        supplier_gid=supplier.gid,
        supplier_name=supplier.name,
        event_type="metric",
        scope_type="supplier_change",
        scope_key=f"{supplier.gid}:method",
        metric="changed",
        entity_type="metric",
        value=2,
    )
    ImporterRunEvent.insert(
        run_gid=run.gid,
        supplier_gid=supplier.gid,
        supplier_name=supplier.name,
        event_type="metric",
        scope_type="supplier_change",
        scope_key=f"{supplier.gid}:product",
        metric="new",
        entity_type="metric",
        value=3,
    )
    ImporterRunEvent.insert(
        run_gid=run.gid,
        supplier_gid=None,
        event_type="metric",
        scope_type="supplier_change",
        scope_key="missing:method",
        metric="changed",
        entity_type="metric",
        value=99,
    )
    ImporterRunEvent.insert(
        run_gid=run.gid,
        supplier_gid=supplier.gid,
        event_type="entity",
        metric="changed",
        entity_type="method",
        entity_olid="method-olid",
        entity_name="Changed method",
    )
    ImporterRunEvent.insert(
        run_gid=run.gid,
        supplier_gid=supplier.gid,
        event_type="entity",
        metric="new",
        entity_type="product",
        entity_olid="product-olid",
        entity_name="New product",
    )
    ImporterRunEvent.insert(
        run_gid=run.gid,
        supplier_gid=unknown_supplier_gid,
        event_type="entity",
        metric="changed",
        entity_type="method",
        entity_name="Unattributed method",
    )
    db_per_file.commit()

    outcomes = kennisnet_import_supplier_outcomes(run.gid)

    assert outcomes == {
        supplier.gid: {
            "supplier_gid": supplier.gid,
            "supplier_name": supplier.name,
            "methods": {"Gewijzigd": 2},
            "products": {"Nieuw": 3},
            "method_examples": {"Gewijzigd": [{"name": "Changed method", "olid": "method-olid"}]},
            "product_examples": {"Nieuw": [{"name": "New product", "olid": "product-olid"}]},
        },
    }


def test_kennisnet_import_validation_errors_groups_sorts_and_filters_invalid_events(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
) -> None:
    """Kennisnet validation reporting should show only well-formed source-row failures."""
    assert migrated_db_per_file is None

    supplier = supplier_factory(name="Validation Supplier", email_domains=["validation.example.test"])
    run = _insert_importer_run(supplier, job_key="kennisnet-validation-errors")
    for details in (
        {"error_details": {"row_index": 8, "messages": ["Naam ontbreekt"]}},
        {
            "error_details": {
                "row_index": 2,
                "messages": ["ISBN ontbreekt"],
                "source_row": {"productId": "source-2", "title": "Voorbeeld"},
            },
        },
        {"error_details": {"row_index": "3", "messages": ["Ongeldige index"]}},
        {"error_details": {"row_index": 4, "messages": "Geen lijst"}},
    ):
        ImporterRunEvent.insert(
            run_gid=run.gid,
            supplier_gid=supplier.gid,
            supplier_name=supplier.name,
            event_type="error",
            metric="row_validation_failed",
            entity_type="product",
            details=details,
        )
    db_per_file.commit()

    errors = kennisnet_import_validation_errors(run.gid)

    assert errors == [
        {
            "supplier_gid": supplier.gid,
            "supplier_name": supplier.name,
            "errors": [
                {
                    "row_index": 2,
                    "messages": ["ISBN ontbreekt"],
                    "source_row": '{\n  "productId": "source-2",\n  "title": "Voorbeeld"\n}',
                },
                {"row_index": 8, "messages": ["Naam ontbreekt"], "source_row": None},
            ],
        },
    ]


def test_build_kennisnet_import_poll_context_reports_queue_lifecycle(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """Kennisnet polling should report pending, completed, failed, and removed PGQ jobs."""
    assert migrated_db_per_file is None

    queued_job_key = str(uuid.uuid4())
    queue_job(
        db_per_file,
        "pytest.kennisnet_import_poll",
        payload={"job_key": queued_job_key},
        unique_key=queued_job_key,
        dill=True,
        execute_after=dt.datetime.now(dt.UTC) + dt.timedelta(hours=1),
    )

    queued = build_kennisnet_import_poll_context(db_per_file, queued_job_key, "/poll/queued")
    db_per_file.executesql(
        "UPDATE pgqueuer SET status = 'picked' WHERE dedupe_key = %(job_key)s",
        placeholders={"job_key": queued_job_key},
    )
    db_per_file.commit()
    running = build_kennisnet_import_poll_context(db_per_file, queued_job_key, "/poll/running")

    completed_job_key = str(uuid.uuid4())
    completed_job = queue_job(
        db_per_file,
        "pytest.kennisnet_import_poll",
        payload={"job_key": completed_job_key},
        unique_key=completed_job_key,
        dill=True,
        execute_after=dt.datetime.now(dt.UTC) + dt.timedelta(hours=1),
    )
    db_per_file.executesql(
        """
        INSERT INTO pgqueuer_result (job_id, entrypoint, result, ok, status, unique_key)
        VALUES (%(job_id)s, %(entrypoint)s, %(result)s::json, %(ok)s, %(status)s, %(job_key)s)
        """,
        placeholders={
            "job_id": completed_job.id,
            "entrypoint": "pytest.kennisnet_import_poll",
            "result": "{}",
            "ok": True,
            "status": "successful",
            "job_key": completed_job_key,
        },
    )
    db_per_file.commit()
    completed = build_kennisnet_import_poll_context(db_per_file, completed_job_key, "/poll/completed")

    failed_job_key = str(uuid.uuid4())
    failed_job = queue_job(
        db_per_file,
        "pytest.kennisnet_import_poll",
        payload={"job_key": failed_job_key},
        unique_key=failed_job_key,
        dill=True,
        execute_after=dt.datetime.now(dt.UTC) + dt.timedelta(hours=1),
    )
    db_per_file.executesql(
        """
        INSERT INTO pgqueuer_result (job_id, entrypoint, result, ok, status, unique_key)
        VALUES (%(job_id)s, %(entrypoint)s, %(result)s::json, %(ok)s, %(status)s, %(job_key)s)
        """,
        placeholders={
            "job_id": failed_job.id,
            "entrypoint": "pytest.kennisnet_import_poll",
            "result": "{}",
            "ok": False,
            "status": "exception",
            "job_key": failed_job_key,
        },
    )
    db_per_file.commit()
    failed = build_kennisnet_import_poll_context(db_per_file, failed_job_key, "/poll/failed")

    missing_job_key = str(uuid.uuid4())
    missing = build_kennisnet_import_poll_context(db_per_file, missing_job_key, "/poll/missing")

    def assert_poll_context(
        context: t.Mapping[str, object],
        *,
        status: str,
        pgqueuer_status: str,
        job_key: str,
        poll_url: str,
    ) -> None:
        assert context["status"] == status
        assert context["pgqueuer_status"] == pgqueuer_status
        assert context["job_key"] == job_key
        assert context["poll_url"] == poll_url
        assert context["progress"] is None

    assert_poll_context(
        queued,
        status="pending",
        pgqueuer_status="queued",
        job_key=queued_job_key,
        poll_url="/poll/queued",
    )
    assert_poll_context(
        running,
        status="pending",
        pgqueuer_status="picked",
        job_key=queued_job_key,
        poll_url="/poll/running",
    )
    assert_poll_context(
        completed,
        status="success",
        pgqueuer_status="successful",
        job_key=completed_job_key,
        poll_url="/poll/completed",
    )
    assert_poll_context(
        failed,
        status="failure",
        pgqueuer_status="exception",
        job_key=failed_job_key,
        poll_url="/poll/failed",
    )
    assert_poll_context(
        missing,
        status="failure",
        pgqueuer_status="missing",
        job_key=missing_job_key,
        poll_url="/poll/missing",
    )


def test_kennisnet_import_result_helpers_query_runs_coverage_and_progress(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
) -> None:
    """Kennisnet result queries should use only aggregate Kennisnet runs."""
    assert migrated_db_per_file is None

    supplier = supplier_factory(name="Kennisnet result supplier", email_domains=["result.example.test"])
    completed_run = _insert_importer_run(supplier, job_key="kennisnet-result-completed")
    completed_run.update_record(source="edu-v-kennisnet-import", payload_json={"trigger": "manual"})
    ImporterRunEvent.insert(
        run_gid=completed_run.gid,
        event_type="observation",
        metric="coverage",
        entity_type="publisher",
        entity_name="Covered publisher",
        details={"publisher": "Covered publisher", "coverage_status": "imported"},
    )

    image_run = _insert_importer_run(supplier, job_key="kennisnet-result-images")
    image_run.update_record(source="edu-v-kennisnet-import", phase="images")
    ImporterRunEvent.insert(
        run_gid=image_run.gid,
        event_type="progress",
        metric="live",
        entity_type="import",
        value=2,
        details={"images_uploaded": 4},
    )
    db_per_file.commit()

    queued_job_key = start_kennisnet_import(db_per_file)
    history = list_kennisnet_import_history_runs()
    coverage = kennisnet_import_coverage(completed_run.gid)

    assert get_kennisnet_import_run(completed_run.gid, extras=()) == get_kennisnet_import_run_by_job_key(
        completed_run.job_key,
        extras=(),
    )
    assert kennisnet_import_run_exists(completed_run.gid)
    assert not kennisnet_import_run_exists(str(uuid.uuid4()))
    assert [run["gid"] for run in history] == [completed_run.gid]
    assert coverage[0] == {
        "label": "Geïmporteerd via Kennisnet",
        "publishers": [{"publisher": "Covered publisher", "coverage_status": "imported"}],
    }
    assert kennisnet_import_progress(image_run.job_key) == {"images_uploaded": 4, "image_suppliers_completed": 2}
    assert kennisnet_import_progress(queued_job_key) is None
