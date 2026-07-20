"""Regression test for py4web auth/RBAC database identity wiring."""

from common.models import db


def test_py4web_auth_rbac_uses_same_db_instance() -> None:
    """The py4web auth RBAC wrapper should reuse the global py4web database object."""
    rbac_db = db.auth.raw_rbac.db
    assert db is rbac_db, f"db {type(db)} {id(db)} != rbac.db {type(rbac_db)} {id(rbac_db)}"
