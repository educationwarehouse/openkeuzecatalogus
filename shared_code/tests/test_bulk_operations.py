"""PostgreSQL integration tests for the shared bulk-operation semaphore."""

import threading
import uuid

import psycopg2
import pytest

from shared_code.data_model import SupplierEd
from shared_code.infra.database import DatabaseContext, advisory_semaphore_context
from shared_code.infra.database.bulk_operations import BULK_OPERATIONS_SEMAPHORE, bulk_operation_context
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.scrapers.eduv.json_import import EduVFileImporter
from shared_code.modules.scrapers.types import ImportStats
from shared_code.util.olid import generate_supplier_olid


def _try_bulk_lock(db: DatabaseContext) -> bool:
    rows = db.executesql(
        "SELECT pg_try_advisory_lock(hashtext(%(namespace)s), hashtext(%(semaphore)s))",
        placeholders={"namespace": "edwh.core", "semaphore": BULK_OPERATIONS_SEMAPHORE},
    )
    acquired = bool(rows[0][0])
    if acquired:
        db.executesql(
            "SELECT pg_advisory_unlock(hashtext(%(namespace)s), hashtext(%(semaphore)s))",
            placeholders={"namespace": "edwh.core", "semaphore": BULK_OPERATIONS_SEMAPHORE},
        )
    return acquired


def test_bulk_lock_survives_transaction_boundaries_and_releases(db_per_file: DatabaseContext) -> None:
    """Other connections stay excluded across commits and rollbacks within a run."""
    observer = DatabaseContext.with_injected(auth_adapter=AuthAdapter.for_service("pytest.bulk.observer"))
    try:
        with bulk_operation_context(db_per_file):
            assert not _try_bulk_lock(observer)
            db_per_file.commit()
            assert not _try_bulk_lock(observer)
            db_per_file.rollback()
            assert not _try_bulk_lock(observer)
        assert _try_bulk_lock(observer)
    finally:
        observer.close()


@pytest.mark.parametrize("sql_failure", [False, True])
def test_bulk_lock_releases_after_failure(db_per_file: DatabaseContext, sql_failure: bool) -> None:
    """Both application errors and aborted SQL transactions release the session lock."""
    observer = DatabaseContext.with_injected(auth_adapter=AuthAdapter.for_service("pytest.bulk.failure_observer"))
    expected_error = psycopg2.Error if sql_failure else ValueError
    try:
        with pytest.raises(expected_error):
            with bulk_operation_context(db_per_file):
                if sql_failure:
                    db_per_file.executesql("SELECT 1 / 0")
                else:
                    raise ValueError("Bulk operation failed")
        assert _try_bulk_lock(observer)
        assert db_per_file.executesql("SELECT 1")[0][0] == 1
    finally:
        observer.close()


def test_bulk_operation_waits_for_shared_semaphore(db_per_file: DatabaseContext) -> None:
    """Independent bulk operations wait on the same semaphore before doing work."""
    waiting = threading.Event()
    entered = threading.Event()
    errors: list[BaseException] = []

    def run_bulk_operation() -> None:
        db = DatabaseContext.with_injected(auth_adapter=AuthAdapter.for_service("pytest.bulk.waiter"))
        try:
            waiting.set()
            with bulk_operation_context(db):
                entered.set()
        except BaseException as error:
            errors.append(error)
        finally:
            db.close()

    thread = threading.Thread(target=run_bulk_operation)
    try:
        with advisory_semaphore_context(db_per_file, semaphore=BULK_OPERATIONS_SEMAPHORE):
            thread.start()
            assert waiting.wait(timeout=5)
            assert not entered.wait(timeout=0.1)
    finally:
        if thread.ident is not None:
            thread.join(timeout=5)

    assert not thread.is_alive()
    assert not errors
    assert entered.is_set()


def test_file_import_holds_bulk_lock_through_entire_lifecycle(db_per_file: DatabaseContext) -> None:
    """The web-upload entrypoint locks before its hooks and retains it after stage commits."""
    supplier_gid = str(uuid.uuid4())
    SupplierEd.insert(
        gid=supplier_gid,
        name="Bulk Lock Supplier",
        olid=generate_supplier_olid(supplier_gid),
        email_domains=[f"{uuid.uuid4().hex}.example.test"],
        endpoint_type="edu-v",
        status_visions="compleet",
    )
    db_per_file.commit()
    observer = DatabaseContext.with_injected(auth_adapter=AuthAdapter.for_service("pytest.bulk.import_observer"))
    completed = threading.Event()

    class LockCheckingFileImporter(EduVFileImporter):
        def before_import(self) -> None:
            assert not _try_bulk_lock(observer)

        def after_methods_and_products_import(self, stats: ImportStats) -> None:
            assert not _try_bulk_lock(observer)

        def after_import(self, stats: ImportStats) -> None:
            assert not _try_bulk_lock(observer)
            completed.set()

    try:
        importer = LockCheckingFileImporter.with_injected(
            db=db_per_file,
            auth_adapter=AuthAdapter.for_service("pytest.bulk.file_import"),
            payload=[],
            version="v2",
            supplier_gid=supplier_gid,
        )
        importer.try_import_into_db(supplier_gid=supplier_gid, endpoint_type="edu-v", mark_removed=False)
        assert completed.is_set()
        assert _try_bulk_lock(observer)
    finally:
        observer.close()
