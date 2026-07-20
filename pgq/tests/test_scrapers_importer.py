"""Importer tests executed in the PGQ suite."""

import uuid
from pathlib import Path

from typedal import TypeDAL

from shared_code.data_model import ImporterRun, ImporterRunErrorStat, Method, MethodEd, Product, ProductEd, SupplierEd
from shared_code.infra.database import database_context
from shared_code.modules.scrapers.eduv import EduVImporter
from shared_code.modules.scrapers.errors import ImportErrorCode
from shared_code.modules.scrapers.flow import rebuild_model
from shared_code.util import olid

FIXTURE_DIR = Path(__file__).parent / "data" / "eduv"
BASE_URL = FIXTURE_DIR.resolve().as_uri()

EDUV_PGQ_SUPPLIER_GID = "e6bbca64-cf76-46d6-a1a4-3a1d61010c66"  # fixed test gid


def _eduv_clean(db: TypeDAL, supplier_gid: str = EDUV_PGQ_SUPPLIER_GID) -> None:
    ProductEd.where(supplier_gid=supplier_gid).delete()
    rebuild_model(db, "product")
    MethodEd.where(supplier_gid=supplier_gid).delete()
    rebuild_model(db, "method")
    SupplierEd.where(gid=supplier_gid).delete()
    rebuild_model(db, "supplier")


def test_eduv_importer_run_imports_fixture_into_database() -> None:
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
            endpoint_base_url=BASE_URL,
            status_visions="compleet",
        )

    try:
        # 2. Importer opens its own database context — no outer context open here
        stats = EduVImporter.run(
            base_url=BASE_URL,
            supplier_gid=EDUV_PGQ_SUPPLIER_GID,
            endpoint_type="edu-v",
            job_key=str(job_key),
            sync_cdn=False,
        )

        assert stats.methods.new == 2
        assert stats.products.new == 3
        assert stats.products.issues == 1

        # 3. Assert in a fresh context
        with database_context("pytest.pgq.scrapers.assert") as db:
            run = ImporterRun.where(ImporterRun.job_key == job_key).first_or_fail()
            products = Product.where(Product.supplier_gid == EDUV_PGQ_SUPPLIER_GID).select().collect()
            methods = Method.where(Method.supplier_gid == EDUV_PGQ_SUPPLIER_GID).select().collect()
            error_rows = ImporterRunErrorStat.where(ImporterRunErrorStat.run_gid == run.gid).select().collect()

            assert run.success is True
            assert len(methods) == 2
            assert len(products) == 3

            happy_product = Product.where(Product.olid == olid.generate("isbn", "9781234567897")).first_or_fail()
            assert happy_product.available == "leverbaar"
            assert happy_product.recommended_price == 12.5

            issue_product = Product.where(Product.olid == olid.generate("eduv", "issue-product-1")).first_or_fail()
            assert issue_product.available == "onbekend"

            method = Method.where(
                Method.olid == olid.generate("method", "fixture publisher:rekenen compleet")
            ).first_or_fail()
            assert method.physical_digital_mix == "mix"
            assert method.tto is True

            assert {row.error_code for row in error_rows} == {
                ImportErrorCode.STATUS_UNKNOWN.value,
                ImportErrorCode.BOUW_PARSE_FAILED.value,
                ImportErrorCode.LICENSE_ACTIVATION_MISSING.value,
            }

    finally:
        # 4. Always clean up, even on assertion failure
        with database_context("pytest.pgq.scrapers.cleanup") as db:
            _eduv_clean(db)
