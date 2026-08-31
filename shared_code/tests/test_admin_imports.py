"""Tests for shared supplier-import admin helpers."""

import datetime as dt
import typing as t

from typedal import TypeDAL

from shared_code.data_model import ImporterRun, ImporterRunCountStat, ImporterRunErrorStat, Supplier
from shared_code.modules.scrapers.admin_imports import (
    build_supplier_runs_context,
    can_start_import,
    format_job_result,
    group_count_rows,
    metric_label,
    run_status,
    serialize_run,
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
    db_per_file.commit()

    assert can_start_import(configured)
    assert not can_start_import(missing_url)


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
    ImporterRunCountStat.insert(
        run_gid=run.gid,
        supplier_gid=supplier.gid,
        supplier_name=supplier.name,
        count_type="method",
        count_key="method-1",
        count_label="Method One",
        metric="seen",
        value=5,
    )
    ImporterRunCountStat.insert(
        run_gid=run.gid,
        supplier_gid=supplier.gid,
        supplier_name=supplier.name,
        count_type="method",
        count_key="method-1",
        count_label="Method One",
        metric="changed",
        value=1,
    )
    ImporterRunCountStat.insert(
        run_gid=run.gid,
        supplier_gid=supplier.gid,
        supplier_name=supplier.name,
        count_type="supplier",
        count_key="supplier-1",
        count_label="Supplier One",
        metric="product_count",
        value=9,
    )
    db_per_file.commit()

    rows = (
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

    assert group_count_rows(rows) == [
        {
            "label": "Method One",
            "metrics": [
                {"label": "Gewijzigd", "value": 1},
                {"label": "Gezien", "value": 5},
            ],
        },
        {
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
    ImporterRunCountStat.insert(
        run_gid=run.gid,
        supplier_gid=supplier.gid,
        supplier_name=supplier.name,
        count_type="method",
        count_key="method-1",
        count_label="Method One",
        metric="seen",
        value=5,
    )
    ImporterRunCountStat.insert(
        run_gid=run.gid,
        supplier_gid=supplier.gid,
        supplier_name=supplier.name,
        count_type="method",
        count_key="method-1",
        count_label="Method One",
        metric="changed",
        value=2,
    )
    ImporterRunErrorStat.insert(
        run_gid=run.gid,
        supplier_gid=supplier.gid,
        supplier_name=supplier.name,
        entity_type="product",
        error_code="missing-name",
        validation_failed=True,
    )
    ImporterRunErrorStat.insert(
        run_gid=run.gid,
        supplier_gid=supplier.gid,
        supplier_name=supplier.name,
        entity_type="product",
        error_code="missing-name",
        validation_failed=True,
    )
    db_per_file.commit()

    serialized = serialize_run(run)
    context = build_supplier_runs_context(supplier)

    assert serialized["status"] == {"label": "Onvolledig", "badge_class": "text-bg-warning"}
    assert serialized["count_groups"] == [
        {
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
    assert run_status(success=False, error_groups=[], warnings=[]) == {"label": "Mislukt", "badge_class": "text-bg-danger"}
    assert run_status(success=True, error_groups=[{"error_code": "x", "count": 1}], warnings=[]) == {
        "label": "Onvolledig",
        "badge_class": "text-bg-warning",
    }
    assert run_status(success=True, error_groups=[], warnings=[]) == {"label": "Succes", "badge_class": "text-bg-success"}
