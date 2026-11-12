"""Integration tests for scraper flow helpers."""

import datetime as dt
import math
import tempfile
import typing as t
import uuid
from pathlib import Path

import pytest
from typedal import TypeDAL

from shared_code.data_model import (
    ImporterRun,
    ImporterRunEvent,
    Method,
    MethodEd,
    Predicate,
    Product,
    ProductEd,
    Supplier,
    SupplierEd,
    Tagged,
    Vision,
)
from shared_code.data_model.constants import get_themes
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.catalog_filters.definitions import BooleanChoiceFilterDefinition, DynamicFieldFilterDefinition
from shared_code.modules.catalog_filters.types import CatalogFilterContext, DynamicFilterMetadata
from shared_code.modules.scrapers.eduv import (
    EduVImporter,
    EduVImporterV2,
    InvalidEduVProductRow,
    TrackedEduVProductV2_0,
)
from shared_code.modules.scrapers.errors import ImportErrorCode
from shared_code.modules.scrapers.flow import (
    ImportFlow,
    _validate_business_fields,
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
    unknown_theme_gid = str(uuid.uuid4())
    vision_olid = generate("vision", vision_gid)
    broken_vision_olid = generate("vision", broken_vision_gid)
    skipped_vision_olid = generate("vision", skipped_vision_gid)
    theme = next(iter(get_themes()))

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
                "onderwijskwaliteit": unknown_theme_gid,
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
                "supplier_gid": supplier.gid,
                "olid": method_olid,
                "name": "Rekenen Basis",
                "available": "leverbaar",
                "levels": [" groep 3 ", "PO", "groep 3", "havo"],
            }
        ],
        products=[
            {
                "gid": product_gid,
                "supplier_gid": supplier.gid,
                "olid": product_olid,
                "name": "Rekenen Werkboek",
                "available": "leverbaar",
                "method_gid": method_gid,
                "method_olid": method_olid,
                "levels": ["groep 4", "PO", "havo"],
            },
            {
                "gid": broken_product_gid,
                "supplier_gid": supplier.gid,
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
    latest_product_ed = (
        ProductEd.where(ProductEd.gid == product_gid).select(orderby=~ProductEd.id, limitby=(0, 1)).first_or_fail()
    )
    assert method.levels == ["havo"]
    assert product.levels == ["havo"]
    assert product.product_family_name is None
    assert product.follow_up_product != "None"  # str none ain't good
    assert latest_product_ed.follow_up_product is None

    error_codes = {row.error_code for row in first_stats.error_stats}
    assert ImportErrorCode.LEVELS_PARSE_FAILED.value in error_codes
    assert ImportErrorCode.ROW_VALIDATION_FAILED.value in error_codes

    changed_stats = flow.import_methods_and_products(
        methods=[
            {
                "gid": method_gid,
                "supplier_gid": supplier.gid,
                "olid": method_olid,
                "name": "Rekenen Basis Vernieuwd",
                "available": "leverbaar",
                "levels": ["groep 3", "havo"],
            }
        ],
        products=[
            {
                "gid": product_gid,
                "supplier_gid": supplier.gid,
                "olid": product_olid,
                "name": "Rekenen Werkboek",
                "available": "beperkt leverbaar",
                "product_family_name": "Rekenen Familie",
                "method_gid": method_gid,
                "method_olid": method_olid,
                "levels": ["groep 4", "havo"],
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
    assert updated_product.product_family_name == "Rekenen Familie"
    assert ProductEd.where(ProductEd.id == latest_product_ed.id).first_or_fail().product_family_name is None


def test_import_validation_excludes_uuid_relationship_identifiers(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """UUID relationship identifiers should not fail business-field validation."""
    assert migrated_db_per_file is None
    assert db_per_file
    supplier_gid = str(uuid.uuid4())
    method_gid = str(uuid.uuid4())

    assert _validate_business_fields(MethodEd, {"supplier_gid": supplier_gid}) == {}
    assert _validate_business_fields(ProductEd, {"supplier_gid": supplier_gid, "method_gid": method_gid}) == {}


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
        ProductEd.where((ProductEd.gid == product_gid) & (ProductEd.prio == ImportPriority.IMPORTER_OK)).select(
            orderby=~ProductEd.id
        )
    )  # cast as list so we can index 0,1,2 instead of by id

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


def _eduv_v2_product(**overrides: t.Any) -> TrackedEduVProductV2_0:
    payload: dict[str, t.Any] = {
        "productId": "9789402054958",
        "publisher": "Test Publisher",
        "type": "digital",
        "status": "available",
        "forSale": True,
        "saleUnitSize": 1,
        "name": "Test Product",
        "edition": "1",
        "studies": [],
        "subjects": [],
        "shortDescription": "Test description",
        "copyrightType": "yes",
        "media": {"publisherThumbnailUrl": {"url": "https://example.test/publisher.jpg"}},
        "firstPublishedDate": "2026-01-01",
        "dateCreated": "2026-01-01T00:00:00Z",
        "dateLastModified": "2026-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return TrackedEduVProductV2_0.model_validate(payload)


def test_eduv_validated_product_keeps_level_years_separate_from_levels() -> None:
    importer = EduVImporterV2(
        base_url="https://catalogus.edu-v.kennisnet.nl/v2/",
        supplier_gid=str(uuid.uuid4()),
    )
    product = _eduv_v2_product(
        studies=[
            {
                "studyName": "Secondary education",
                "studyLevels": [
                    {"studyLevelId": str(uuid.uuid4()), "studyLevelPrefix": "0000", "studyLevelName": level}
                    for level in ("havo 4", "havo 5", "havo 4", "vwo, 5")
                ],
            }
        ]
    )

    product_data = importer._convert_validated_product(product)

    assert product_data["level_x_year"] == ["havo 4", "havo 5", "vwo 5"]
    assert product_data["levels"] == ["havo", "vwo"]


@pytest.mark.parametrize(
    ("level_names", "expected_bouw", "expected_tto"),
    [
        (["havo 1", "vwo 3"], ["onderbouw"], False),
        (["havo 4", "vwo 6"], ["bovenbouw"], False),
        (["havo 3", "havo 4"], ["bovenbouw", "onderbouw"], False),
        # Synthetic compatibility cases; Edu-V does not define these TTO study level names.
        (["havo tto 4", "vwo TTO 5"], ["bovenbouw"], True),
        (["havo-tto 2"], ["onderbouw"], True),
        (["havo", "vwo"], [], False),
        ([], [], False),
    ],
)
def test_eduv_product_and_method_bouw_and_tto(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    level_names: list[str],
    expected_bouw: list[str],
    expected_tto: bool,
) -> None:
    """Import both catalogue entities with Bouw and TTO derived from study levels."""
    assert migrated_db_per_file is None
    supplier_gid = str(uuid.uuid4())
    SupplierEd.insert(
        gid=supplier_gid,
        name="Bouw TTO Supplier",
        olid=generate_supplier_olid(supplier_gid),
        email_domains=[f"{uuid.uuid4().hex}.example.test"],
        endpoint_type="none",
        status_visions="compleet",
    )
    db_per_file.commit()
    importer = EduVImporterV2(base_url="https://catalogus.edu-v.kennisnet.nl/v2/", supplier_gid=supplier_gid)
    product = _eduv_v2_product(
        productId=str(uuid.uuid4()),
        publisher=f"Bouw TTO Publisher {supplier_gid}",
        studies=[
            {
                "studyName": "Secondary education",
                "studyLevels": [
                    {"studyLevelId": str(uuid.uuid4()), "studyLevelPrefix": "0000", "studyLevelName": level}
                    for level in level_names
                ],
            }
        ],
    )

    product_data = importer._convert_validated_product(product)
    assert product_data["bouw"] == expected_bouw
    assert product_data["tto"] is expected_tto
    if expected_tto:
        assert all("tto" not in level.lower() for level in product_data["levels"])
        assert product_data["levels"]

    methods = importer._build_methods_from_products([product_data])
    assert len(methods) == 1
    assert methods[0]["bouw"] == expected_bouw
    assert methods[0]["tto"] is expected_tto

    flow = ImportFlow.with_injected(db=db_per_file)
    stats = flow.import_methods_and_products(
        methods=methods,
        products=[product_data],
        prio=ImportPriority.IMPORTER_OK,
        last_saved_by="pytest.bouw_tto",
        mark_removed=False,
    )
    assert stats.products.issues == 0
    assert stats.methods.issues == 0
    builder = Product.where(Product.supplier_gid == supplier_gid)
    imported = builder.collect().first()
    assert imported is not None
    assert imported.bouw == expected_bouw
    assert imported.tto is expected_tto
    context = CatalogFilterContext(entity_kind="product", table=Product, params={}, option_builder=builder)
    bouw = DynamicFieldFilterDefinition(
        DynamicFilterMetadata(
            slug="bouw",
            label="Bouw",
            filter_kind="dynamic",
            field_name="bouw",
            match_mode="contains",
            applies_to="product",
            handler_key=None,
            widget_kind="select",
            sort_order=1,
        ),
        context,
    )
    tto = BooleanChoiceFilterDefinition(
        DynamicFilterMetadata(
            slug="tto",
            label="TTO",
            filter_kind="custom",
            field_name="tto",
            handler_key="boolean_choice",
            match_mode="belongs",
            applies_to="product",
            widget_kind="select",
            sort_order=2,
        ),
        context,
    )
    assert [option.value for option in bouw.options()] == expected_bouw
    assert [(option.value, option.label) for option in tto.options()] == [("T", "Ja") if expected_tto else ("F", "Nee")]
    for value in expected_bouw:
        assert bouw.apply(builder, [value]).count() == 1
    assert tto.apply(builder, "T" if expected_tto else "F").count() == 1
    assert tto.apply(builder, "F" if expected_tto else "T").count() == 0


@pytest.mark.parametrize(
    ("family_name", "expected_family", "expected_name"),
    [
        ("  Test Family  ", "Test Family", "Test Family"),
        ("  ", None, "Test Product"),
        ("", None, "Test Product"),
        (None, None, "Test Product"),
    ],
)
def test_eduv_method_identity_strips_whitespace(
    family_name: str | None, expected_family: str | None, expected_name: str
) -> None:
    importer = EduVImporterV2(base_url="https://catalogus.edu-v.kennisnet.nl/v2/")
    product = _eduv_v2_product(publisher="  Test Publisher  ", productFamilyName=family_name)

    product_data = importer._convert_validated_product(product)

    assert product_data["product_family_name"] == expected_family
    assert product_data["method_name"] == expected_name
    assert product_data["method_olid"] == generate("method", f"test publisher:{expected_name.lower()}")


@pytest.mark.parametrize(
    ("family_name", "expected_family", "expected_name"),
    [
        ("  Test Family  ", "Test Family", "Test Family"),
        ("  ", None, "Test Product"),
        ("", None, "Test Product"),
        (None, None, "Test Product"),
    ],
)
def test_eduv_invalid_product_keeps_normalized_method_identity(
    family_name: str | None, expected_family: str | None, expected_name: str
) -> None:
    importer = EduVImporterV2(
        base_url="https://catalogus.edu-v.kennisnet.nl/v2/",
        supplier_gid=str(uuid.uuid4()),
    )
    invalid: InvalidEduVProductRow = {
        "_index": 1,
        "_row": {
            "productId": "9789402054958",
            "publisher": "  Test Publisher  ",
            "name": "Test Product",
            "productFamilyName": family_name,
        },
        "_errors": [ImportErrorCode.ROW_VALIDATION_FAILED],
        "_validation_errors": [],
    }

    product_data = importer._convert_failing_product(invalid)

    assert product_data["product_family_name"] == expected_family
    assert product_data["method_name"] == expected_name
    assert product_data["method_olid"] == generate("method", f"test publisher:{expected_name.lower()}")


def test_eduv_missing_product_family_does_not_use_the_product_name() -> None:
    importer = EduVImporterV2(base_url="https://catalogus.edu-v.kennisnet.nl/v2/")

    product_data = importer._convert_validated_product(_eduv_v2_product())

    assert product_data["product_family_name"] is None
    assert product_data["method_name"] == "Test Product"


def test_eduv_product_references_are_unique_in_source_order() -> None:
    importer = EduVImporterV2(base_url="https://catalogus.edu-v.kennisnet.nl/v2/")
    first_id = "9789402054965"
    second_id = "9789402054972"
    product = _eduv_v2_product(
        bundledProducts=[first_id, second_id, first_id],
        relatedProducts=[second_id, first_id, second_id],
    )

    product_data = importer._convert_validated_product(product)

    assert product_data["bundle_product_olids"] == [
        generate("product", first_id),
        generate("product", second_id),
    ]
    assert product_data["related_product_olids"] == [
        generate("product", second_id),
        generate("product", first_id),
    ]


def test_eduv_recommended_price_uses_typed_prices() -> None:
    importer = EduVImporterV2(base_url="https://catalogus.edu-v.kennisnet.nl/v2/")
    today = dt.date.today()
    prices = [
        {"priceExcl": amount, "priceIncl": amount, "priceCurrency": "EUR", "validFrom": date.isoformat()}
        for amount, date in (
            (9.99, today - dt.timedelta(days=30)),
            (10.99, today),
            (12.99, today + dt.timedelta(days=1)),
        )
    ]
    product = _eduv_v2_product(price=prices)

    assert importer._extract_recommended_price(product) == 10.99

    future_product = _eduv_v2_product(price=prices[2:])
    assert importer._extract_recommended_price(future_product) == 12.99


def test_eduv_typed_media_and_license_helpers() -> None:
    importer = EduVImporterV2(base_url="https://catalogus.edu-v.kennisnet.nl/v2/")
    product = _eduv_v2_product(
        media={
            "publisherThumbnailUrl": {"url": "https://example.test/publisher.jpg"},
            "mainThumbnailUrl": {"url": "https://example.test/main.jpg"},
        },
        licensePeriod={"licenseVariant": "days", "licenseDays": 365},
    )

    assert importer._extract_image_url(product) == "https://example.test/main.jpg"
    assert importer._extract_license_duration(product) == "365 dagen"

    activation_product = _eduv_v2_product(activationPeriod={"activationVariant": "schoolyear"})
    assert importer._extract_license_duration(activation_product) == "activation:schoolyear"


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
                "supplier_gid": supplier.gid,
                "olid": method_olid,
                "name": "Link Resolution Method",
                "available": "leverbaar",
            }
        ],
        products=[
            {
                "gid": source_product_gid,
                "supplier_gid": supplier.gid,
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
                "supplier_gid": supplier.gid,
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
    linked_gid = linked_product.gid

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
            db=db_per_file,
            base_url=fixture_dir.as_uri(),
            supplier_gid=supplier.gid,
            auth_adapter=AuthAdapter.for_service("pytest.eduv_v2_999"),
        )

        job_key = f"pytest-eduv-warning-{uuid.uuid4().hex}"

        stats = importer.try_import_into_db(
            supplier_gid=supplier.gid,
            endpoint_type="edu-v",
            job_key=job_key,
            mark_removed=False,
        )

    assert any(w.warning_code == "eduv_newer_version" for w in stats.warning_stats)

    run = ImporterRun.where(ImporterRun.job_key == job_key).first()
    assert run is not None
    assert ImporterRunEvent.where(run_gid=run.gid, event_type="warning", metric="eduv_newer_version").exists()


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
        supplier_gid=supplier.gid,
        db=db_per_file,
        image_storage=MockImageStorage(tmp_path / "cdn"),
        auth_adapter=AuthAdapter.for_service("pytest.scraper_flow"),
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
        supplier_gid=supplier.gid,
        supplier_name=supplier.name,
        job_key=f"pytest-image-stats-{uuid.uuid4().hex}",
        started_at=now,
        finished_at=now,
        success=True,
        payload_json={},
        stats=ImportStats(image_uploads=image_stats),
        warnings=importer._warnings,
    )
    count_rows = ImporterRunEvent.where(
        (ImporterRunEvent.run_gid == run_gid)
        & (ImporterRunEvent.event_type == "metric")
        & (ImporterRunEvent.scope_key == "image_upload")
    ).select(ImporterRunEvent.metric, ImporterRunEvent.value)

    assert {row.metric: int(row.value) for row in count_rows} == {
        "attempted": 2,
        "uploaded": 1,
        "failed": 1,
        "skipped": 0,
    }
    run = ImporterRun.where(ImporterRun.gid == run_gid).first_or_fail()
    assert ImporterRunEvent.where(run_gid=run.gid, event_type="warning", metric="image_upload_failed").exists()


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
        supplier_gid=supplier.gid,
        olid=f"run-log-method-two-{suffix}",
        name="Method With Two Products",
    )
    method_one = method_factory(
        supplier_gid=supplier.gid,
        olid=f"run-log-method-one-{suffix}",
        name="Method With One Product",
    )
    method_zero = method_factory(
        supplier_gid=supplier.gid,
        olid=f"run-log-method-zero-{suffix}",
        name="Method Without Products",
    )

    for index, method_gid in enumerate([method_two.gid, method_two.gid, method_one.gid]):
        product_factory(
            supplier_gid=supplier.gid,
            method_gid=method_gid,
            olid=f"run-log-product-{suffix}-{index}",
            name=f"Run Log Product {index}",
        )

    methods = [method_two, method_one, method_zero]

    # The pre-refactor implementation, kept here as the reference to compare against.
    expected_counts = {method.gid: Product.where(Product.method_gid == method.gid).count() for method in methods}
    assert sorted(expected_counts.values()) == [0, 1, 2], "fixture should cover zero, one and many"

    now = dt.datetime.now()
    run_gid = record_importer_run(
        db_per_file,
        source="pytest-run-log-counts",
        endpoint_type="edu-v",
        supplier_gid=supplier.gid,
        supplier_name=supplier.name,
        job_key=f"pytest-run-log-counts-{suffix}",
        started_at=now,
        finished_at=now,
        success=True,
        payload_json={},
        stats=ImportStats(),
    )

    method_count_rows = ImporterRunEvent.where(
        (ImporterRunEvent.run_gid == run_gid)
        & (ImporterRunEvent.event_type == "metric")
        & (ImporterRunEvent.scope_type == "method")
        & (ImporterRunEvent.metric == "product_count"),
    ).select(ImporterRunEvent.scope_key, ImporterRunEvent.value)

    recorded_counts = {row.scope_key: int(row.value) for row in method_count_rows}
    assert recorded_counts == expected_counts

    supplier_count_rows = ImporterRunEvent.where(
        (ImporterRunEvent.run_gid == run_gid)
        & (ImporterRunEvent.event_type == "metric")
        & (ImporterRunEvent.scope_type == "supplier"),
    ).select(ImporterRunEvent.metric, ImporterRunEvent.value)

    recorded_supplier_counts = {row.metric: int(row.value) for row in supplier_count_rows}
    assert recorded_supplier_counts["method_count"] == len(methods)
    assert recorded_supplier_counts["product_count"] == sum(expected_counts.values())
