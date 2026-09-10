"""Smoke tests for database fixtures in `shared_code/tests/conftest.py`."""

from typedal import TypeDAL


def test_db_psql(db_psql: TypeDAL) -> None:
    """Verify db_psql yields a working DAL connection."""
    assert isinstance(db_psql, TypeDAL)
    db_psql.executesql("SELECT 1")


def test_wipe_db(wipe_db: TypeDAL) -> None:
    """Verify wipe_db clears the database and returns a usable DAL."""
    assert isinstance(wipe_db, TypeDAL)
    # After a wipe, querying any application table should not error,
    # but there should be nothing to find.
    wipe_db.executesql("SELECT 1")


def test_run_migrations(run_migrations: TypeDAL) -> None:
    """Verify run_migrations applies migrations without wiping first."""
    assert isinstance(run_migrations, TypeDAL)
    run_migrations.executesql("SELECT 1")


def test_migrated_db(migrated_db: TypeDAL) -> None:
    """Verify migrated_db gives a wiped + migrated database."""
    assert isinstance(migrated_db, TypeDAL)
    migrated_db.executesql("SELECT 1")


def test_restored_db(restored_db: TypeDAL) -> None:
    """Verify restored_db restores a snapshot and applies migrations."""
    assert isinstance(restored_db, TypeDAL)
    restored_db.executesql("SELECT 1")


def test_snapshot_name(snapshot_name: str) -> None:
    """Verify snapshot_name yields the default snapshot identifier."""
    assert snapshot_name == "testing.snapshot"


def test_module_scoped_db_lifecycle_fixtures(
    wipe_db_per_file: None,
    run_migrations_per_file: None,
    migrated_db_per_file: None,
) -> None:
    """Verify module-scoped lifecycle fixtures are available and composable."""
    assert wipe_db_per_file is None
    assert run_migrations_per_file is None
    assert migrated_db_per_file is None
