"""Integration tests for scraper flow helpers."""

import math
import uuid

import pytest
from typedal import TypeDAL

from shared_code.data_model import Method, Product, ProductEd, Supplier, Vision, SupplierEd
from shared_code.modules.scrapers.errors import ImportErrorCode
from shared_code.modules.scrapers.flow import (
    _values_differ,
    import_methods_and_products,
    insert_into_effdt_if_changed_for_prio,
    upsert_suppliers,
    upsert_visions,
)
from shared_code.modules.scrapers.types import ChangeStatus, ImportPriority
from shared_code.util.olid import generate, generate_supplier_olid


def test_upsert_suppliers_handles_new_changed_unchanged_and_invalid_rows(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """Supplier upserts should persist valid rows and reject invalid payloads."""
    assert migrated_db_per_file is None

    supplier_flow_gid = str(uuid.uuid4())
    supplier_broken_gid = str(uuid.uuid4())
    supplier_missing_gid = str(uuid.uuid4())
    supplier_flow_olid = generate_supplier_olid(supplier_flow_gid)
    supplier_broken_olid = generate_supplier_olid(supplier_broken_gid)
    supplier_missing_olid = generate_supplier_olid(supplier_missing_gid)

    first_stats = upsert_suppliers(
        db_per_file,
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

    unchanged_stats = upsert_suppliers(
        db_per_file,
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

    changed_stats = upsert_suppliers(
        db_per_file,
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

    vision_gid = str(uuid.uuid4())
    broken_vision_gid = str(uuid.uuid4())
    skipped_vision_gid = str(uuid.uuid4())
    vision_olid = generate("vision", vision_gid)
    broken_vision_olid = generate("vision", broken_vision_gid)
    skipped_vision_olid = generate("vision", skipped_vision_gid)
    theme = "kwaliteit-effectiviteit"

    first_stats = upsert_visions(
        db_per_file,
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

    unchanged_stats = upsert_visions(
        db_per_file,
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

    changed_stats = upsert_visions(
        db_per_file,
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

    first_stats = import_methods_and_products(
        db_per_file,
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
    assert method.levels == ["PO"]
    assert product.levels == ["PO"]

    error_codes = {row.error_code for row in first_stats.error_stats}
    assert ImportErrorCode.LEVELS_PARSE_FAILED.value in error_codes
    assert ImportErrorCode.ROW_VALIDATION_FAILED.value in error_codes

    changed_stats = import_methods_and_products(
        db_per_file,
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

    assert changed_stats.methods.changed == 1
    assert changed_stats.products.changed == 1
    assert changed_stats.methods.issues == 0
    assert changed_stats.products.issues == 0

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

    unchanged = insert_into_effdt_if_changed_for_prio(
        Product,
        product_gid,
        {"gid": product_gid, "recommended_price": 10.004},
        prio=ImportPriority.IMPORTER_OK,
        last_saved_by="pytest.scrapers.flow",
    )
    assert unchanged.status is ChangeStatus.UNCHANGED

    changed = insert_into_effdt_if_changed_for_prio(
        Product,
        product_gid,
        {"gid": product_gid, "recommended_price": 10.01},
        prio=ImportPriority.IMPORTER_OK,
        last_saved_by="pytest.scrapers.flow",
    )
    assert changed.status is ChangeStatus.CHANGED

    status_flip = insert_into_effdt_if_changed_for_prio(
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
        insert_into_effdt_if_changed_for_prio(
            Product,
            product_gid,
            {"gid": str(uuid.uuid4()), "recommended_price": 10.01},
            prio=ImportPriority.IMPORTER_OK,
            last_saved_by="pytest.scrapers.flow",
        )
