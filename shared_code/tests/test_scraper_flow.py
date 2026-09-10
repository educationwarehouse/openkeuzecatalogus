"""Integration tests for scraper flow helpers."""

import datetime as dt
import math
import tempfile
import typing as t
import uuid
from pathlib import Path

import pytest
from shared_code.modules.auth import AuthAdapter
from typedal import TypeDAL

from shared_code.data_model import (
    ImporterRun,
    ImporterRunCountStat,
    Method,
    MethodEd,
    Product,
    ProductEd,
    Supplier,
    SupplierEd,
    Vision, Tagged, Predicate,
)
from shared_code.modules.scrapers.eduv import EduVImporter, EduVImporterV2
from shared_code.modules.scrapers.errors import ImportErrorCode
from shared_code.modules.scrapers.flow import (
    ImportFlow,
    _values_differ,
)
from shared_code.modules.scrapers.run_log import record_importer_run
from shared_code.modules.scrapers.types import ChangeStatus, ImportPriority, ImportStats
from shared_code.services.images import MockImageStorage
from shared_code.util.olid import generate, generate_supplier_olid


def test_upsert_suppliers_handles_new_changed_unchanged_and_invalid_rows(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """Supplier upserts should persist valid rows and reject invalid payloads."""
    assert migrated_db_per_file is None
    flow = ImportFlow.with_injected(db=db_per_file)

    supplier_flow_gid = str(uuid.uuid4())
    supplier_broken_gid = str(uuid.uuid4())
    supplier_missing_gid = str(uuid.uuid4())
    supplier_flow_olid = generate_supplier_olid(supplier_flow_gid)
    supplier_broken_olid = generate_supplier_olid(supplier_broken_gid)
    supplier_missing_olid = generate_supplier_olid(supplier_missing_gid)

    first_stats = flow.upsert_suppliers(
        [
            {
                "gid": supplier_flow_gid,
                "name": "Flow Supplier",
                "olid": supplier_flow_olid,
                "status_visions": "compleet",
                "logo_url": "https://example.test/supplier.svg",
            },
            {
                "gid": supplier_broken_gid,
                "name": "Broken Supplier",
                "olid": supplier_broken_olid,
                "status_visions": "not-a-real-status",
            },
            {
                "gid": supplier_missing_gid,
                "name": "Missing Vision Status",
                "olid": supplier_missing_olid,
            },
        ],
        last_saved_by="pytest.scrapers.suppliers",
    )

    assert first_stats.seen == 3
    assert first_stats.imported == 1
    assert first_stats.issues == 2

    inserted = Supplier.where(Supplier.olid == supplier_flow_olid).first_or_fail()
    assert inserted.name == "Flow Supplier"
    assert inserted.status_visions == "compleet"

    unchanged_stats = flow.upsert_suppliers(
        [
            {
                "gid": supplier_flow_gid,
                "name": "Flow Supplier",
                "olid": supplier_flow_olid,
                "status_visions": "compleet",
                "logo_url": "https://example.test/supplier.svg",
            }
        ],
        last_saved_by="pytest.scrapers.suppliers",
    )
    assert unchanged_stats.seen == 1
    assert unchanged_stats.imported == 0
    assert unchanged_stats.issues == 0

    changed_stats = flow.upsert_suppliers(
        [
            {
                "gid": supplier_flow_gid,
                "name": "Flow Supplier Renamed",
                "olid": supplier_flow_olid,
                "status_visions": "compleet",
                "logo_url": "https://example.test/supplier-v2.svg",
            }
        ],
        last_saved_by="pytest.scrapers.suppliers",
    )
    assert changed_stats.seen == 1
    assert changed_stats.imported == 1
    assert changed_stats.issues == 0

    updated = Supplier.where(Supplier.olid == supplier_flow_olid).first_or_fail()
    assert updated.name == "Flow Supplier Renamed"
    assert updated.logo_url == "https://example.test/supplier-v2.svg"


def test_upsert_visions_handles_new_changed_unchanged_and_invalid_rows(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """Vision upserts should key by `(olid, onderwijskwaliteit)` and validate themes."""
    assert migrated_db_per_file is None
    flow = ImportFlow.with_injected(db=db_per_file)

    vision_gid = str(uuid.uuid4())
    broken_vision_gid = str(uuid.uuid4())
    skipped_vision_gid = str(uuid.uuid4())
    vision_olid = generate("vision", vision_gid)
    broken_vision_olid = generate("vision", broken_vision_gid)
    skipped_vision_olid = generate("vision", skipped_vision_gid)
    theme = "kwaliteit-effectiviteit"

    first_stats = flow.upsert_visions(
        [
            {
                "gid": vision_gid,
                "olid": vision_olid,
                "onderwijskwaliteit": theme,
                "visie": "Eerste visie op kwaliteit.",
            },
            {
                "gid": broken_vision_gid,
                "olid": broken_vision_olid,
                "onderwijskwaliteit": "not-a-real-theme",
                "visie": "Ongeldige visie.",
            },
            {
                "gid": skipped_vision_gid,
                "olid": skipped_vision_olid,
                "onderwijskwaliteit": theme,
            },
        ],
        prio=ImportPriority.IMPORTER_OK,
        last_saved_by="pytest.scrapers.visions",
    )

    assert first_stats.seen == 3
    assert first_stats.imported == 1
    assert first_stats.issues == 1

    inserted = Vision.where((Vision.olid == vision_olid) & (Vision.onderwijskwaliteit == theme)).first_or_fail()
    assert inserted.visie == "Eerste visie op kwaliteit."

    unchanged_stats = flow.upsert_visions(
        [
            {
                "gid": vision_gid,
                "olid": vision_olid,
                "onderwijskwaliteit": theme,
                "visie": "Eerste visie op kwaliteit.",
            }
        ],
        prio=ImportPriority.IMPORTER_OK,
        last_saved_by="pytest.scrapers.visions",
    )
    assert unchanged_stats.imported == 0
    assert unchanged_stats.issues == 0

    changed_stats = flow.upsert_visions(
        [
            {
                "gid": vision_gid,
                "olid": vision_olid,
                "onderwijskwaliteit": theme,
                "visie": "Bijgewerkte visie op kwaliteit.",
            }
        ],
        prio=ImportPriority.IMPORTER_OK,
        last_saved_by="pytest.scrapers.visions",
    )
    assert changed_stats.imported == 1
    assert changed_stats.issues == 0

    updated = Vision.where((Vision.olid == vision_olid) & (Vision.onderwijskwaliteit == theme)).first_or_fail()
    assert updated.visie == "Bijgewerkte visie op kwaliteit."


def test_import_methods_and_products_tracks_changes_errors_and_level_normalization(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """Importer flow should persist methods/products and report row-level issues."""
    assert migrated_db_per_file is None
    flow = ImportFlow.with_injected(db=db_per_file)

    supplier_gid = str(uuid.uuid4())
    supplier = SupplierEd.insert(
        gid=supplier_gid,
        name="Flow Import Supplier",
        olid=generate_supplier_olid(supplier_gid),
        email_domains=[f"{uuid.uuid4().hex}.example.test"],
        endpoint_type="none",
        status_visions="compleet",
    )
    db_per_file.commit()

    method_gid = str(uuid.uuid4())
    product_gid = str(uuid.uuid4())
    broken_product_gid = str(uuid.uuid4())
    method_olid = generate("method", method_gid)
    product_olid = generate("product", product_gid)
    broken_product_olid = generate("product", broken_product_gid)

    first_stats = flow.import_methods_and_products(
        methods=[
            {
                "gid": method_gid,
                "supplier_gid": str(supplier.gid),
                "olid": method_olid,
                "name": "Rekenen Basis",
                "available": "leverbaar",
                "levels": [" groep 3 ", "PO", "groep 3"],
            }
        ],
        products=[
            {
                "gid": product_gid,
                "supplier_gid": str(supplier.gid),
                "olid": product_olid,
                "name": "Rekenen Werkboek",
                "available": "leverbaar",
                "method_gid": method_gid,
                "method_olid": method_olid,
                "levels": ["groep 4", "PO"],
            },
            {
                "gid": broken_product_gid,
                "supplier_gid": str(supplier.gid),
                "olid": broken_product_olid,
                "name": "Ongeldig Product",
                "available": "definitely-invalid",
                "method_gid": method_gid,
                "_errors": [ImportErrorCode.LEVELS_PARSE_FAILED],
            },
        ],
        prio=ImportPriority.IMPORTER_OK,
        last_saved_by="pytest.scrapers.import",
        mark_removed=False,
    )

    assert first_stats.methods.seen == 1
    assert first_stats.methods.new == 1
    assert first_stats.methods.issues == 0
    assert first_stats.products.seen == 2
    assert first_stats.products.new == 1
    assert first_stats.products.issues == 1

    method = Method.where(Method.olid == method_olid).first_or_fail()
    product = Product.where(Product.olid == product_olid).first_or_fail()
    latest_product_ed = ProductEd.where(ProductEd.gid == product_gid).select(orderby=~ProductEd.id, limitby=(0, 1)).first_or_fail()
    assert method.levels == ["PO"]
    assert product.levels == ["PO"]
    assert product.follow_up_product != "None"  # str none ain't good
    assert latest_product_ed.follow_up_product is None

    error_codes = {row.error_code for row in first_stats.error_stats}
    assert ImportErrorCode.LEVELS_PARSE_FAILED.value in error_codes
    assert ImportErrorCode.ROW_VALIDATION_FAILED.value in error_codes

    changed_stats = flow.import_methods_and_products(
        methods=[
            {
                "gid": method_gid,
                "supplier_gid": str(supplier.gid),
                "olid": method_olid,
                "name": "Rekenen Basis Vernieuwd",
                "available": "leverbaar",
                "levels": ["groep 3"],
            }
        ],
        products=[
            {
                "gid": product_gid,
                "supplier_gid": str(supplier.gid),
                "olid": product_olid,
                "name": "Rekenen Werkboek",
                "available": "beperkt leverbaar",
                "method_gid": method_gid,
                "method_olid": method_olid,
                "levels": ["groep 4"],
            }
        ],
        prio=ImportPriority.IMPORTER_OK,
        last_saved_by="pytest.scrapers.import",
        mark_removed=False,
    )

    assert changed_stats.products.issues == 0, f"product has issues: {changed_stats.error_stats}"
    assert changed_stats.methods.changed == 1
    assert changed_stats.products.changed == 1
    assert changed_stats.methods.issues == 0

    updated_method = Method.where(Method.olid == method_olid).first_or_fail()
    updated_product = Product.where(Product.olid == product_olid).first_or_fail()
    assert updated_method.name == "Rekenen Basis Vernieuwd"
    assert updated_product.available == "beperkt leverbaar"


def test_insert_into_effdt_ignores_numeric_noise_but_detects_real_change(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """Effective-dated imports should ignore tolerated numeric drift and track real changes."""
    assert migrated_db_per_file is None
    assert _values_differ(10.0, 10.004) is False
    assert _values_differ(10.0, 10.01) is True
    assert _values_differ(math.nan, math.nan) is True
    flow = ImportFlow.with_injected(db=db_per_file)

    supplier_gid = str(uuid.uuid4())
    product_gid = str(uuid.uuid4())
    supplier = SupplierEd.insert(
        gid=supplier_gid,
        name="Scraper Flow Supplier",
        olid=generate_supplier_olid(supplier_gid),
        email_domains=[f"{uuid.uuid4().hex}.example.test"],
        endpoint_type="none",
        status_visions="compleet",
    )
    product_olid = generate("product", product_gid)
    ProductEd.insert(
        gid=product_gid,
        olid=product_olid,
        name="Tolerance Product",
        available="leverbaar",
        supplier_gid=supplier.gid,
        method_gid=str(uuid.uuid4()),
        recommended_price=10.0,
        prio=ImportPriority.IMPORTER_OK,
        effstatus=True,
    )
    db_per_file.commit()

    unchanged = flow.insert_into_effdt_if_changed_for_prio(
        Product,
        product_gid,
        {"gid": product_gid, "recommended_price": 10.004},
        prio=ImportPriority.IMPORTER_OK,
        last_saved_by="pytest.scrapers.flow",
    )
    assert unchanged.status is ChangeStatus.UNCHANGED

    changed = flow.insert_into_effdt_if_changed_for_prio(
        Product,
        product_gid,
        {"gid": product_gid, "recommended_price": 10.01},
        prio=ImportPriority.IMPORTER_OK,
        last_saved_by="pytest.scrapers.flow",
    )
    assert changed.status is ChangeStatus.CHANGED

    status_flip = flow.insert_into_effdt_if_changed_for_prio(
        Product,
        product_gid,
        {"gid": product_gid, "recommended_price": 10.01},
        prio=ImportPriority.IMPORTER_OK,
        last_saved_by="pytest.scrapers.flow",
        effstatus=False,
    )
    assert status_flip.status is ChangeStatus.CHANGED

    latest_rows = list(
        ProductEd.where((ProductEd.gid == product_gid) & (ProductEd.prio == ImportPriority.IMPORTER_OK))
        .select(orderby=~ProductEd.id)
    ) # cast as list so we can index 0,1,2 instead of by id

    assert len(latest_rows) == 3
    assert latest_rows[0].recommended_price == 10.01
    assert latest_rows[0].effstatus is False
    assert latest_rows[1].recommended_price == 10.01
    assert latest_rows[1].effstatus is True
    assert latest_rows[2].recommended_price == 10.0
    assert latest_rows[2].effstatus is True

    with pytest.raises(ValueError, match="incoming_data.gid"):
        flow.insert_into_effdt_if_changed_for_prio(
            Product,
            product_gid,
            {"gid": str(uuid.uuid4()), "recommended_price": 10.01},
            prio=ImportPriority.IMPORTER_OK,
            last_saved_by="pytest.scrapers.flow",
        )


def test_eduv_raw_row_keeps_level_years_separate_from_levels() -> None:
    """Edu-V rows should populate normalized levels and full level-year values separately."""
    importer = EduVImporterV2(
        base_url="https://catalogus.edu-v.kennisnet.nl/v2/",
        supplier_gid=str(uuid.uuid4()),
    )

    product_data = importer._build_import_product_from_raw_row(
        {
            "productId": "level-separation-product",
            "name": "Level Separation Product",
            "status": "available",
            "studies": [
                {
                    "studyLevels": [
                        {"studyLevelName": "havo 4"},
                        {"studyLevelName": "havo 5"},
                        {"studyLevelName": "havo 4"},
                        {"studyLevelName": "vwo 5"},
                    ]
                }
            ],
        }
    )

    assert product_data["level_x_year"] == ["havo 4", "havo 5", "vwo 5"]
    assert product_data["levels"] == ["havo", "vwo"]


def test_import_products_resolves_links_to_products_later_in_same_batch(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """Product links should resolve even when the linked product row appears later."""
    assert migrated_db_per_file is None
    flow = ImportFlow.with_injected(db=db_per_file)

    supplier_gid = str(uuid.uuid4())
    supplier = SupplierEd.insert(
        gid=supplier_gid,
        name="Flow Link Supplier",
        olid=generate_supplier_olid(supplier_gid),
        email_domains=[f"{uuid.uuid4().hex}.example.test"],
        endpoint_type="none",
        status_visions="compleet",
    )
    db_per_file.commit()

    method_gid = str(uuid.uuid4())
    method_olid = generate("method", method_gid)

    source_product_gid = str(uuid.uuid4())
    source_product_olid = generate("product", source_product_gid)
    linked_product_gid = str(uuid.uuid4())
    linked_product_olid = generate("product", linked_product_gid)

    stats = flow.import_methods_and_products(
        methods=[
            {
                "gid": method_gid,
                "supplier_gid": str(supplier.gid),
                "olid": method_olid,
                "name": "Link Resolution Method",
                "available": "leverbaar",
            }
        ],
        products=[
            {
                "gid": source_product_gid,
                "supplier_gid": str(supplier.gid),
                "olid": source_product_olid,
                "name": "Source Product",
                "available": "leverbaar",
                "method_gid": method_gid,
                "method_olid": method_olid,
                "follow_up_product_olid": linked_product_olid,
                "bundle_product_olids": [linked_product_olid],
                "related_product_olids": [linked_product_olid],
            },
            {
                "gid": linked_product_gid,
                "supplier_gid": str(supplier.gid),
                "olid": linked_product_olid,
                "name": "Linked Product",
                "available": "leverbaar",
                "method_gid": method_gid,
                "method_olid": method_olid,
            },
        ],
        prio=ImportPriority.IMPORTER_OK,
        last_saved_by="pytest.scrapers.import.links",
        mark_removed=False,
    )

    assert stats.products.issues == 0

    source_product = Product.where(Product.olid == source_product_olid).first_or_fail()
    linked_product = Product.where(Product.olid == linked_product_olid).first_or_fail()
    linked_gid = str(linked_product.gid)

    assert str(source_product.follow_up_product) == linked_gid
    assert Tagged.lookup(source_product.gid, Predicate.BUNDLES, None) == [linked_gid]
    assert [str(gid) for gid in source_product.related_products] == [linked_gid]
    assert source_product.composition == "package"
    assert linked_product.composition == "component"


def test_eduv_variant_propagates_warning_to_run_stats_and_log(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """Edu-V importer runs should persist endpoint-version warnings."""
    assert migrated_db_per_file is None

    supplier_gid = str(uuid.uuid4())
    supplier = SupplierEd.insert(
        gid=supplier_gid,
        name="EduV Warning Supplier",
        olid=generate_supplier_olid(supplier_gid),
        email_domains=[f"{uuid.uuid4().hex}.example.test"],
        endpoint_type="edu-v",
        status_visions="compleet",
    )
    db_per_file.commit()

    with tempfile.TemporaryDirectory(prefix="eduv-") as tmp_dir:
        fixture_dir = Path(tmp_dir) / "v2.999"
        fixture_dir.mkdir()
        (fixture_dir / "products.json").write_text('{"products": []}', encoding="utf-8")

        importer = EduVImporter.with_injected(
            base_url=fixture_dir.as_uri(),
            supplier_gid=str(supplier.gid),
            auth_adapter=AuthAdapter.for_service("pytest.eduv_v2_999"),
        )

        job_key = f"pytest-eduv-warning-{uuid.uuid4().hex}"

        stats = importer.try_import_into_db(
            supplier_gid=str(supplier.gid),
            endpoint_type="edu-v",
            job_key=job_key,
            mark_removed=False,
        )

    assert any(w.warning_code == "eduv_newer_version" for w in stats.warning_stats)

    run = ImporterRun.where(ImporterRun.job_key == job_key).first()
    assert run is not None
    warnings_json = run.warnings_json or []
    assert any(str(entry.get("warning_code")) == "eduv_newer_version" for entry in warnings_json)


def test_cdn_image_upload_stats_track_success_failure_and_run_counts(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Image sync should count successful and failed CDN uploads in the importer run."""
    assert migrated_db_per_file is None
    monkeypatch.setenv("IMAGE_STORAGE_HASH_SALT", "pytest-image-stats")

    supplier_gid = str(uuid.uuid4())
    supplier = SupplierEd.insert(
        gid=supplier_gid,
        name="Image Stats Supplier",
        olid=generate_supplier_olid(supplier_gid),
        email_domains=[f"{uuid.uuid4().hex}.example.test"],
        endpoint_type="edu-v",
        status_visions="compleet",
    )
    method_gid = str(uuid.uuid4())
    successful_source = tmp_path / "source.jpg"
    successful_source.write_bytes(b"image bytes")
    failed_source = tmp_path / "missing.jpg"

    for isbn, image_url in (
        ("9789402054958", successful_source.as_uri()),
        ("9789402054959", failed_source.as_uri()),
    ):
        ProductEd.insert(
            gid=str(uuid.uuid4()),
            olid=generate("product", isbn),
            isbn=isbn,
            name=f"Image product {isbn}",
            available="leverbaar",
            supplier_gid=supplier.gid,
            method_gid=method_gid,
            image_url=image_url,
            prio=ImportPriority.IMPORTER_OK,
            effstatus=True,
        )
    db_per_file.commit()

    importer = EduVImporterV2.with_injected(
        base_url="https://catalogus.edu-v.kennisnet.nl/v2/",
        supplier_gid=str(supplier.gid),
        db=db_per_file,
        image_storage=MockImageStorage(tmp_path / "cdn"),
        auth_adapter=AuthAdapter.for_service("pytest.scraper_flow")
    )

    image_stats = importer.sync_images_to_cdn()

    assert image_stats.attempted == 2
    assert image_stats.uploaded == 1
    assert image_stats.failed == 1
    assert any(warning.warning_code == "image_upload_failed" for warning in importer._warnings)

    now = dt.datetime.now()
    run_gid = record_importer_run(
        db_per_file,
        source=importer.source,
        endpoint_type="edu-v",
        supplier_gid=str(supplier.gid),
        supplier_name=str(supplier.name),
        job_key=f"pytest-image-stats-{uuid.uuid4().hex}",
        started_at=now,
        finished_at=now,
        success=True,
        payload_json={},
        stats=ImportStats(image_uploads=image_stats),
        warnings=importer._warnings,
    )
    count_rows = ImporterRunCountStat.where(
        (ImporterRunCountStat.run_gid == run_gid) & (ImporterRunCountStat.count_key == "image_upload")
    ).select(ImporterRunCountStat.metric, ImporterRunCountStat.value)

    assert {str(row.metric): int(row.value) for row in count_rows} == {
        "attempted": 2,
        "uploaded": 1,
        "failed": 1,
        "skipped": 0,
    }
    run = ImporterRun.where(ImporterRun.gid == run_gid).first_or_fail()
    assert any(entry.get("warning_code") == "image_upload_failed" for entry in run.warnings_json or [])


def test_run_log_method_product_counts_match_per_method_counting(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
) -> None:
    """Grouped per-method product counts must equal counting each method separately.

    `_snapshot_supplier_method_counts` used to run one COUNT per method. The grouped query that
    replaced it returns no row at all for methods without products, so the zero-product method
    below is the case that actually guards the rewrite.
    """
    assert migrated_db_per_file is None

    supplier = supplier_factory(name="Run Log Supplier", email_domains=["run-log-counts.example.test"])
    suffix = uuid.uuid4().hex[:8]

    method_two = method_factory(
        supplier_gid=str(supplier.gid),
        olid=f"run-log-method-two-{suffix}",
        name="Method With Two Products",
    )
    method_one = method_factory(
        supplier_gid=str(supplier.gid),
        olid=f"run-log-method-one-{suffix}",
        name="Method With One Product",
    )
    method_zero = method_factory(
        supplier_gid=str(supplier.gid),
        olid=f"run-log-method-zero-{suffix}",
        name="Method Without Products",
    )

    for index, method_gid in enumerate([method_two.gid, method_two.gid, method_one.gid]):
        product_factory(
            supplier_gid=str(supplier.gid),
            method_gid=method_gid,
            olid=f"run-log-product-{suffix}-{index}",
            name=f"Run Log Product {index}",
        )

    methods = [method_two, method_one, method_zero]

    # The pre-refactor implementation, kept here as the reference to compare against.
    expected_counts = {str(method.gid): Product.where(Product.method_gid == method.gid).count() for method in methods}
    assert sorted(expected_counts.values()) == [0, 1, 2], "fixture should cover zero, one and many"

    now = dt.datetime.now()
    run_gid = record_importer_run(
        db_per_file,
        source="pytest-run-log-counts",
        endpoint_type="edu-v",
        supplier_gid=str(supplier.gid),
        supplier_name=str(supplier.name),
        job_key=f"pytest-run-log-counts-{suffix}",
        started_at=now,
        finished_at=now,
        success=True,
        payload_json={},
        stats=ImportStats(),
    )

    method_count_rows = ImporterRunCountStat.where(
        (ImporterRunCountStat.run_gid == run_gid)
        & (ImporterRunCountStat.count_type == "method")
        & (ImporterRunCountStat.metric == "product_count"),
    ).select(ImporterRunCountStat.count_key, ImporterRunCountStat.value)

    recorded_counts = {str(row.count_key): int(row.value) for row in method_count_rows}
    assert recorded_counts == expected_counts

    supplier_count_rows = ImporterRunCountStat.where(
        (ImporterRunCountStat.run_gid == run_gid) & (ImporterRunCountStat.count_type == "supplier"),
    ).select(ImporterRunCountStat.metric, ImporterRunCountStat.value)

    recorded_supplier_counts = {str(row.metric): int(row.value) for row in supplier_count_rows}
    assert recorded_supplier_counts["method_count"] == len(methods)
    assert recorded_supplier_counts["product_count"] == sum(expected_counts.values())
