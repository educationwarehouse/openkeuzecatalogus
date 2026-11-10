"""Integration tests for materialized-view maintenance."""

import threading
import typing as t

from shared_code.infra.database import DatabaseContext, advisory_semaphore_context
from shared_code.infra.database.materialized_views import refresh_all_materialized_views
from shared_code.modules.auth import AuthAdapter


def test_all_materialized_views_can_refresh_concurrently(db_per_file: DatabaseContext) -> None:
    """Every project materialized view must have the unique index concurrent refresh requires."""
    non_concurrent_views = db_per_file.executesql(
        "SELECT mview FROM materialized_views WHERE NOT is_concurrent;",
        colnames=["mview"],
    )

    assert not non_concurrent_views, (
        "Materialized views without a unique index cannot refresh concurrently: "
        f"{', '.join(row.mview for row in non_concurrent_views)}"
    )


def test_refresh_all_materialized_views_waits_for_its_semaphore() -> None:
    """A second refresh must wait until the first refresh releases its semaphore."""
    semaphore_acquired = threading.Event()
    release_semaphore = threading.Event()
    refresh_finished = threading.Event()
    errors: list[BaseException] = []

    def hold_semaphore() -> None:
        db = DatabaseContext.with_injected(
            auth_adapter=AuthAdapter.for_service("pytest.materialized_views.semaphore_holder")
        )
        try:
            with advisory_semaphore_context(db, semaphore="refresh_all_materialized_views"):
                semaphore_acquired.set()
                assert release_semaphore.wait(timeout=5)
        except BaseException as error:
            errors.append(error)
        finally:
            db.close()

    def refresh_views() -> None:
        db = DatabaseContext.with_injected(
            auth_adapter=AuthAdapter.for_service("pytest.materialized_views.semaphore_refresh")
        )
        try:
            refresh_all_materialized_views(db)
            refresh_finished.set()
        except BaseException as error:
            errors.append(error)
        finally:
            db.close()

    semaphore_thread = threading.Thread(target=hold_semaphore)
    refresh_thread = threading.Thread(target=refresh_views)
    semaphore_thread.start()

    try:
        assert semaphore_acquired.wait(timeout=5)
        refresh_thread.start()
        assert not refresh_finished.wait(timeout=0.1)
    finally:
        release_semaphore.set()
        semaphore_thread.join(timeout=5)
        refresh_thread.join(timeout=5)

    assert not semaphore_thread.is_alive()
    assert not refresh_thread.is_alive()
    assert not errors
    assert refresh_finished.is_set()
