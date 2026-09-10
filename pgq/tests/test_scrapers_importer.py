"""Importer tests executed in the PGQ suite."""

import json
import uuid
import warnings
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from typedal import TypeDAL

from shared_code.data_model import ImporterRun, Method, MethodEd, Product, ProductEd, SupplierEd
from shared_code.infra.database import database_context
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.scrapers.eduv import EduVFileVersion, EduVImporter
from shared_code.modules.scrapers.eduv.generated import catalogue_v1_1_0, catalogue_v2_0_0
from shared_code.modules.scrapers.eduv.json_import import EduVFileImporter, default_eduv_file_version
from shared_code.modules.scrapers.flow import rebuild_model
from shared_code.util import olid

FIXTURE_DIR = Path(__file__).parent / "data" / "eduv"
BASE_URL_V1 = (FIXTURE_DIR / "v1.1.0").resolve().as_uri()
BASE_URL_V2 = (FIXTURE_DIR / "v2.0.0").resolve().as_uri()

EDUV_PGQ_SUPPLIER_GID = "e6bbca64-cf76-46d6-a1a4-3a1d61010c66"  # fixed test gid

ERROR_UNUSED_FIELDS = "unused top-level fields"
STRICT_UNUSED = True


def _assert_no_unused_field_debug_output(output: str) -> None:
    matching_lines = [line for line in output.splitlines() if ERROR_UNUSED_FIELDS in line]
    if STRICT_UNUSED:
        assert not matching_lines, "\n".join(matching_lines)
    else:
        warnings.warn("\n".join(matching_lines), stacklevel=0)


def _eduv_clean(db: TypeDAL, supplier_gid: str = EDUV_PGQ_SUPPLIER_GID) -> None:
    ProductEd.where(supplier_gid=supplier_gid).delete()
    rebuild_model(db, "product")
    MethodEd.where(supplier_gid=supplier_gid).delete()
    rebuild_model(db, "method")
    SupplierEd.where(gid=supplier_gid).delete()
    rebuild_model(db, "supplier")


@pytest.fixture
def prepare_eduv_importer_data() -> Iterator[Callable[[str], None]]:
    """Clean registered supplier data before and after an importer integration test."""
    supplier_gids: set[str] = set()

    def prepare(supplier_gid: str) -> None:
        supplier_gids.add(supplier_gid)
        with database_context("pytest.pgq.scrapers.fixture_setup") as db:
            _eduv_clean(db, supplier_gid)

    yield prepare

    with database_context("pytest.pgq.scrapers.fixture_cleanup") as db:
        for supplier_gid in supplier_gids:
            _eduv_clean(db, supplier_gid)


@pytest.mark.parametrize(
    ("fixture_path", "product_model"),
    [
        (FIXTURE_DIR / "v1.1.0" / "products.json", catalogue_v1_1_0.Product),
        (FIXTURE_DIR / "v2.0.0" / "products.json", catalogue_v2_0_0.Product),
    ],
)
def test_eduv_products_fixtures_match_catalogue_schema(
    fixture_path: Path,
    product_model: type[catalogue_v1_1_0.Product | catalogue_v2_0_0.Product],
) -> None:
    """Fixture products must validate against the matching versioned catalogue schema."""
    payload = json.loads(fixture_path.read_text())

    assert isinstance(payload.get("products"), list)
    for row in payload["products"]:
        product_model.model_validate(row)


def test_eduv_v2_importer_filters_fixture_products_by_endpoint_publisher() -> None:
    """Edu-V v2 importer should drop products whose publisher does not match the configured filter."""
    importer = EduVImporter.with_injected(
        base_url=BASE_URL_V2,
        supplier_gid=EDUV_PGQ_SUPPLIER_GID,
        endpoint_publisher="Malmberg",
        auth_adapter=AuthAdapter.for_service("pytest.eduv_v2"),
    )

    products = importer.fetch_products()
    methods = importer.fetch_methods()

    assert len(products) == 1
    assert products[0]["isbn"] == "9789402054958"
    assert products[0]["name"] == "Biologie voor jou 4 havo/vwo leerboek"

    assert len(methods) == 1
    assert methods[0]["name"] == "Biologie voor jou"


@pytest.mark.parametrize(
    ("version", "fixture_directory", "base_url"),
    [
        ("v1", "v1.1.0", BASE_URL_V1),
        ("v2", "v2.0.0", BASE_URL_V2),
    ],
)
def test_eduv_file_importer_matches_endpoint_importer_for_valid_fixture(
    version: EduVFileVersion,
    fixture_directory: str,
    base_url: str,
) -> None:
    """Uploaded catalogues use the same schema validation and normalization as endpoints."""
    payload = json.loads((FIXTURE_DIR / fixture_directory / "products.json").read_text())
    endpoint_importer = EduVImporter.with_injected(
        base_url=base_url,
        supplier_gid=EDUV_PGQ_SUPPLIER_GID,
        auth_adapter=AuthAdapter.for_service(f"pytest.eduv_{version}"),
    )
    file_importer = EduVFileImporter(
        payload=payload,
        version=version,
        supplier_gid=EDUV_PGQ_SUPPLIER_GID,
    )

    assert file_importer.fetch_products() == endpoint_importer.fetch_products()
    assert file_importer.fetch_methods() == endpoint_importer.fetch_methods()
    assert file_importer.validation_errors() == []


def test_eduv_file_importer_filters_products_by_endpoint_publisher() -> None:
    """Uploaded catalogues retain the endpoint publisher filter."""
    payload = json.loads((FIXTURE_DIR / "v2.0.0" / "products.json").read_text())
    importer = EduVFileImporter(
        payload=payload,
        version="v2",
        supplier_gid=EDUV_PGQ_SUPPLIER_GID,
        endpoint_publisher="Malmberg",
    )

    products = importer.fetch_products()
    methods = importer.fetch_methods()

    assert len(products) == 1
    assert products[0]["isbn"] == "9789402054958"
    assert len(methods) == 1
    assert methods[0]["name"] == "Biologie voor jou"


def test_eduv_file_importer_reports_invalid_rows_and_excludes_them_from_import() -> None:
    """An invalid uploaded row is shown in the preview and never reaches the import flow."""
    payload = json.loads((FIXTURE_DIR / "v2.0.0" / "products.json").read_text())
    del payload["products"][0]["productId"]
    importer = EduVFileImporter(
        payload=payload,
        version="v2",
        supplier_gid=EDUV_PGQ_SUPPLIER_GID,
    )

    products = importer.fetch_products()
    errors = importer.validation_errors()

    assert len(products) == 1
    assert len(errors) == 1
    assert errors[0].index == 1
    assert any(message.startswith("productId:") for message in errors[0].messages)


def test_eduv_file_importer_keeps_source_index_for_invalid_rows() -> None:
    """Schema errors must point to the original product row in an uploaded file."""
    payload = json.loads((FIXTURE_DIR / "v2.0.0" / "products.json").read_text())
    del payload["products"][1]["productId"]
    importer = EduVFileImporter(
        payload=payload,
        version="v2",
        supplier_gid=EDUV_PGQ_SUPPLIER_GID,
    )

    errors = importer.validation_errors()

    assert len(errors) == 1
    assert errors[0].index == 2


def test_eduv_file_importer_archives_items_omitted_from_a_later_file(
    prepare_eduv_importer_data: Callable[[str], None],
) -> None:
    """A later uploaded file marks its supplier's omitted products and methods as removed."""
    supplier_gid = str(uuid.uuid4())
    payload = json.loads((FIXTURE_DIR / "v2.0.0" / "products.json").read_text())
    retained_product_id = payload["products"][0]["productId"]
    removed_product_id = payload["products"][1]["productId"]
    retained_product_olid = olid.generate("product", retained_product_id)
    removed_product_olid = olid.generate("product", removed_product_id)
    removed_method_olid = olid.generate("method", "noordhoff:getal en ruimte")
    prepare_eduv_importer_data(supplier_gid)

    with database_context("pytest.pgq.eduv_file_import.setup") as db:
        SupplierEd.insert(
            gid=supplier_gid,
            name="Edu-V File Import Supplier",
            email_domains=[f"{uuid.uuid4().hex}.example.test"],
            endpoint_type="edu-v",
            status_visions="compleet",
        )

    with database_context("pytest.pgq.eduv_file_import.import") as db:
        full_importer = EduVFileImporter.with_injected(
            db=db,
            auth_adapter=AuthAdapter.for_service("pytest.eduv_file_import"),
            payload=payload,
            version="v2",
            supplier_gid=supplier_gid,
        )
        initial_stats = full_importer.import_methods_and_products(
            prio=full_importer.priority,
            last_saved_by="pytest.eduv_file_import",
        )

        subset_importer = EduVFileImporter.with_injected(
            db=db,
            auth_adapter=AuthAdapter.for_service("pytest.eduv_file_import"),
            payload={"products": [payload["products"][0]]},
            version="v2",
            supplier_gid=supplier_gid,
        )
        removal_stats = subset_importer.import_methods_and_products(
            prio=subset_importer.priority,
            last_saved_by="pytest.eduv_file_import",
        )

        retained_product = Product.where(Product.olid == retained_product_olid).first_or_fail()
        removed_product = Product.where(Product.olid == removed_product_olid).first_or_fail()
        removed_method = Method.where(Method.olid == removed_method_olid).first_or_fail()

    assert initial_stats.products.new == 2
    assert removal_stats.methods.removed == 1
    assert removal_stats.products.removed == 1
    assert retained_product.available == "leverbaar"
    assert removed_product.available == "verwijderd"
    assert removed_method.available == "verwijderd"


def test_automatic_eduv_import_keeps_unrelated_supplier_items_available(
    prepare_eduv_importer_data: Callable[[str], None],
) -> None:
    """Automatic imports only mark items from their own supplier as removed."""
    imported_supplier_gid = str(uuid.uuid4())
    unrelated_supplier_gid = str(uuid.uuid4())
    prepare_eduv_importer_data(imported_supplier_gid)
    prepare_eduv_importer_data(unrelated_supplier_gid)

    with database_context("pytest.pgq.eduv_supplier_scope.setup") as db:
        for supplier_gid, name in (
            (imported_supplier_gid, "Imported Edu-V Supplier"),
            (unrelated_supplier_gid, "Unrelated Edu-V Supplier"),
        ):
            SupplierEd.insert(
                gid=supplier_gid,
                name=name,
                email_domains=[f"{uuid.uuid4().hex}.example.test"],
                endpoint_type="edu-v",
                status_visions="compleet",
            )

    unrelated_payload = json.loads((FIXTURE_DIR / "v1.1.0" / "products.json").read_text())
    unrelated_product = unrelated_payload["products"][0]
    unrelated_product["productId"] = "9789402054996"
    unrelated_product["publisher"] = "Unrelated Publisher"
    unrelated_product["productFamilyName"] = "Unrelated Method"

    with database_context("pytest.pgq.eduv_supplier_scope.import") as db:
        unrelated_importer = EduVImporter.with_injected(
            db=db,
            auth_adapter=AuthAdapter.for_service("pytest.eduv_supplier_scope.v1"),
            base_url=BASE_URL_V1,
            supplier_gid=unrelated_supplier_gid,
        )
        unrelated_importer._products_cache = [unrelated_product]
        unrelated_importer.import_into_db()

        imported_importer = EduVImporter.with_injected(
            db=db,
            auth_adapter=AuthAdapter.for_service("pytest.eduv_supplier_scope.v2"),
            base_url=BASE_URL_V2,
            supplier_gid=imported_supplier_gid,
        )
        imported_importer.import_into_db()

        unrelated_products = Product.where(Product.supplier_gid == unrelated_supplier_gid).collect()
        unrelated_methods = Method.where(Method.supplier_gid == unrelated_supplier_gid).collect()

    assert len(unrelated_products) == 1
    assert len(unrelated_methods) == 1
    assert unrelated_products[0].available == "leverbaar"
    assert unrelated_methods[0].available == "leverbaar"


@pytest.mark.parametrize(
    ("endpoint_base_url", "expected_version"),
    [
        ("https://catalogus.edu-v.kennisnet.nl/v1/", "v1"),
        ("https://catalogus.edu-v.kennisnet.nl/v2/", "v2"),
        (None, None),
    ],
)
def test_default_eduv_file_version_follows_supplier_endpoint(
    endpoint_base_url: str | None,
    expected_version: EduVFileVersion | None,
) -> None:
    """The upload form defaults to the version configured for the supplier endpoint."""
    assert default_eduv_file_version(endpoint_base_url) == expected_version


def test_eduv_importer_run_imports_fixture_into_database(capsys: pytest.CaptureFixture[str]) -> None:
    """Edu-V importer should read fixture data and persist methods, products, and run logs."""
    job_key = uuid.uuid7()

    # 1. Clean + set up; context closes before the importer runs
    with database_context("pytest.pgq.scrapers.setup") as db:
        _eduv_clean(db)
        SupplierEd.insert(
            gid=EDUV_PGQ_SUPPLIER_GID,
            name="Fixture Publisher",
            email_domains=[f"{uuid.uuid4().hex}.example.test"],
            endpoint_type="edu-v",
            endpoint_base_url=BASE_URL_V1,
            status_visions="compleet",
        )

    try:
        # 2. Importer opens its own database context — no outer context open here
        stats = EduVImporter.run(
            base_url=BASE_URL_V1,
            supplier_gid=EDUV_PGQ_SUPPLIER_GID,
            endpoint_type="edu-v",
            job_key=str(job_key),
        )

        with database_context("pytest.pgq.scrapers.error_rows") as db:
            run = ImporterRun.where(ImporterRun.job_key == job_key).join("error_stats").first_or_fail()

        assert stats.products.issues == 0, f"product has issues: {run.error_stats.as_list()}"
        assert stats.methods.new == 1
        assert stats.products.new == 1

        stdio = capsys.readouterr()
        _assert_no_unused_field_debug_output(stdio.out)
        _assert_no_unused_field_debug_output(stdio.err)

        # 3. Assert in a fresh context
        with database_context("pytest.pgq.scrapers.assert") as db:
            run = ImporterRun.where(ImporterRun.job_key == job_key).join("error_stats").first_or_fail()
            products = Product.where(Product.supplier_gid == EDUV_PGQ_SUPPLIER_GID).collect()
            methods = Method.where(Method.supplier_gid == EDUV_PGQ_SUPPLIER_GID).collect()

            assert run.success is True
            assert len(methods) == 1
            assert len(products) == 1
            assert len(run.error_stats) == 0

            happy_product = Product.where(Product.olid == olid.generate("isbn", "9789402054958")).first_or_fail()
            assert happy_product.available == "leverbaar"
            assert happy_product.recommended_price == 31.43
            assert happy_product.image_url.startswith("file:///shared_cache/image_uploads/")
            assert not happy_product.image_url.startswith("file:///pythonpath/")

            method = Method.where(Method.olid == olid.generate("method", "malmberg:biologie voor jou")).first_or_fail()
            assert method.physical_digital_mix == "mix"
            assert method.tto is False

    finally:
        # 4. Always clean up, even on assertion failure
        with database_context("pytest.pgq.scrapers.cleanup") as db:
            _eduv_clean(db)


def test_eduv_v2_importer_run_imports_fixture_into_database(capsys: pytest.CaptureFixture[str]) -> None:
    """Edu-V v2 importer should read fixture data and persist methods, products, and run logs."""
    job_key = uuid.uuid7()

    # 1. Clean + set up; context closes before the importer runs
    with database_context("pytest.pgq.scrapers.setup") as db:
        _eduv_clean(db)
        SupplierEd.insert(
            gid=EDUV_PGQ_SUPPLIER_GID,
            name="Fixture Publisher",
            email_domains=[f"{uuid.uuid4().hex}.example.test"],
            endpoint_type="edu-v",
            endpoint_base_url=BASE_URL_V2,
            status_visions="compleet",
        )

    try:
        # 2. Importer opens its own database context — no outer context open here
        stats = EduVImporter.run(
            base_url=BASE_URL_V2,
            supplier_gid=EDUV_PGQ_SUPPLIER_GID,
            endpoint_type="edu-v",
            job_key=str(job_key),
        )

        assert stats.methods.new == 2
        assert stats.products.new == 2
        assert stats.products.issues == 0

        stdio = capsys.readouterr()
        _assert_no_unused_field_debug_output(stdio.out)
        _assert_no_unused_field_debug_output(stdio.err)

        # 3. Assert in a fresh context
        with database_context("pytest.pgq.scrapers.assert") as db:
            run = ImporterRun.where(ImporterRun.job_key == job_key).join("error_stats").first_or_fail()
            products = Product.where(Product.supplier_gid == EDUV_PGQ_SUPPLIER_GID).collect()
            methods = Method.where(Method.supplier_gid == EDUV_PGQ_SUPPLIER_GID).collect()
            error_rows = run.error_stats

            assert run.success is True
            assert len(methods) == 2
            assert len(products) == 2

            happy_product = Product.where(Product.olid == olid.generate("isbn", "9789402054958")).first_or_fail()
            assert happy_product.available == "leverbaar"
            assert happy_product.recommended_price == 31.43

            method = Method.where(Method.olid == olid.generate("method", "malmberg:biologie voor jou")).first_or_fail()
            assert method.physical_digital_mix == "mix"
            assert method.tto is False

            assert len(error_rows) == 0

    finally:
        # 4. Always clean up, even on assertion failure
        with database_context("pytest.pgq.scrapers.cleanup") as db:
            _eduv_clean(db)
