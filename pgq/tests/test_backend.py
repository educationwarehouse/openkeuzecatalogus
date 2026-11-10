"""Tests for PGQ backend lifecycle management."""

import gc
import weakref

from pgq.backend import pgq_backend
from shared_code.data_model import AuthUser
from shared_code.services.deferred import PgqDeferredWork


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


def test_pgq_deferred_work_decodes_json_results_without_losing_unexpected_values() -> None:
    """Stored PGQ values preserve nulls, non-text values, and malformed JSON safely."""
    assert PgqDeferredWork._decode_result(None) is None
    assert PgqDeferredWork._decode_result({"already": "decoded"}) == {"already": "decoded"}
    assert PgqDeferredWork._decode_result(b'{"status": "done"}') == {"status": "done"}
    assert PgqDeferredWork._decode_result('["first", 2]') == ["first", 2]
    assert PgqDeferredWork._decode_result("not-json") == "not-json"

    with pgq_backend("pytest.pgq.backend2") as backend:
        assert AuthUser._db is backend.db
        assert AuthUser.email.requires

        db_reference = weakref.ref(backend.db)

    gc.collect()

    assert AuthUser._db is None
    assert not getattr(AuthUser.email, "requires", None)
    assert db_reference() is None
