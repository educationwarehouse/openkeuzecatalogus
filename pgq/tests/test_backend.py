"""Tests for PGQ backend lifecycle management."""

import gc
import weakref

from pgq.backend import pgq_backend
from shared_code.data_model import AuthUser


def test_pgq_backend_releases_database_context() -> None:
    """The database context is closed and released after each PGQ job.

    This prevents hanging tests and PGQ workers. The lifecycle is exercised twice
    to verify that cleaned database references are correctly rebuilt for a new
    context and released again afterward.

    When this test fails, something still holds a reference to the database.
    TypeDAL cleans up known references, such as database references in validators
    like IS_IN_SET(), but unknown use cases may still retain one.

    Use gc.get_referrers(db) to help identify remaining references.
    """
    with pgq_backend("pytest.pgq.backend") as backend:
        assert AuthUser._db is backend.db
        assert AuthUser.email.requires

        db_reference = weakref.ref(backend.db)

    gc.collect()

    assert AuthUser._db is None
    assert not getattr(AuthUser.email, "requires", None)
    assert db_reference() is None

    with pgq_backend("pytest.pgq.backend2") as backend:
        assert AuthUser._db is backend.db
        assert AuthUser.email.requires

        db_reference = weakref.ref(backend.db)

    gc.collect()

    assert AuthUser._db is None
    assert not getattr(AuthUser.email, "requires", None)
    assert db_reference() is None
