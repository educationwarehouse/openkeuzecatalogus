"""Shared pytest fixtures for shared_code tests."""

import os
import secrets
import shutil
import string
import subprocess
import typing as t
import warnings
from pathlib import Path
from urllib.parse import urlparse

import pytest
from typedal import TypeDAL

from shared_code.data_model.setup import define_tables
from shared_code.services.database import database_context

DEFAULT_SNAPSHOT_NAME = "testing.snapshot"

# Snapshot directory: bind-mounted from ./migrate/data → /data in the container.
SNAPSHOTS_DIR = Path("/data")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_postgres_uri(uri: str) -> dict[str, str]:
    """Parse a pydal-style postgres URI into connection parameters."""
    parsed = urlparse(uri)
    return {
        "user": parsed.username or "",
        "password": parsed.password or "",
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "dbname": (parsed.path or "/").lstrip("/"),
    }


def _build_psql_env() -> dict[str, str]:
    """Return a subprocess env dict with PG* variables for psql/pg_restore."""
    postgres_uri = os.environ.get("POSTGRES_URI") or os.environ.get("MIGRATE_URI", "")
    if not postgres_uri:
        raise RuntimeError("POSTGRES_URI or MIGRATE_URI is required for database fixtures.")
    pg = _parse_postgres_uri(postgres_uri)
    env = os.environ.copy()
    env.update(
        PGUSER=pg["user"],
        PGPASSWORD=pg["password"],
        PGHOST=pg["host"],
        PGPORT=pg["port"],
        PGDATABASE=pg["dbname"],
    )
    return env


def _run_psql(sql: str) -> subprocess.CompletedProcess[bytes]:
    """Execute raw SQL via psql using environment-based auth."""
    env = _build_psql_env()
    return subprocess.run(
        ["psql", "-v", "ON_ERROR_STOP=1", "-c", sql],
        env=env,
        check=True,
        capture_output=True,
    )


def _wipe_all_schemas() -> None:
    """Drop all user-created schemas and recreate them empty via psql."""
    schema_filter = """
    nspname NOT IN ('information_schema')
    AND nspname NOT LIKE 'pg_%'
    """

    # query_schemas = f"""
    #     SELECT nspname
    #       FROM pg_namespace
    #      WHERE {schema_filter};
    # """
    # result = _run_psql(query_schemas)
    # print(f"[wipe_db] dropping schemas:")
    # print(result.stdout.decode().strip())

    _run_psql(
        f"""
        DO $$
        DECLARE
            r RECORD;
        BEGIN
            FOR r IN
                SELECT nspname
                  FROM pg_namespace
                 WHERE {schema_filter}
            LOOP
                EXECUTE format('DROP SCHEMA IF EXISTS %I CASCADE', r.nspname);
            END LOOP;
        END $$;
        """
    )

    _run_psql("CREATE SCHEMA IF NOT EXISTS public;")


def _run_migrate_subprocess() -> None:
    """Invoke the edwh-migrate CLI as a subprocess, mirroring the compose service."""
    env = os.environ.copy()

    # Remove stale lock files so pending migrations actually execute.
    flag_dir = Path(os.environ.get("FLAG_LOCATION", "/flags"))
    if flag_dir.is_dir():
        for lock_file in flag_dir.glob("migrate-*.complete"):
            lock_file.unlink()

    result = subprocess.run(
        ["migrate"],
        env=env,
        capture_output=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        raise RuntimeError(f"migration subprocess failed:\n{stderr}")


def _run_pg_restore(snapshot_dir: Path) -> None:
    """Restore a pg_dump directory-format snapshot into the current database."""
    pg = _parse_postgres_uri(os.environ.get("POSTGRES_URI", ""))
    env = {**os.environ, "PGPASSWORD": pg["password"]}
    result = subprocess.run(
        [
            "pg_restore",
            "--exit-on-error",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            "-h",
            pg["host"],
            "-p",
            pg["port"],
            "-U",
            pg["user"],
            "-d",
            pg["dbname"],
            str(snapshot_dir),
        ],
        env=env,
        capture_output=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        raise RuntimeError(f"pg_restore failed:\n{stderr}")


def _random_snapshot_suffix(length: int = 6) -> str:
    """Return a short random alphanumeric suffix."""
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ---------------------------------------------------------------------------
# Base fixtures (existing)
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_psql() -> t.Iterator[TypeDAL]:
    """Fresh Postgres TypeDAL instance per test."""
    postgres_uri = os.environ.get("POSTGRES_URI")
    if not postgres_uri:
        raise RuntimeError("POSTGRES_URI is required for shared_code tests.")

    database = TypeDAL(postgres_uri)
    try:
        yield database
    finally:
        database.close()


@pytest.fixture()
def db(db_psql: TypeDAL) -> TypeDAL:
    """TypeDAL instance with all shared data-model tables defined.

    Function-scoped
    """
    return define_tables(db_psql)


# ---------------------------------------------------------------------------
# Database lifecycle fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def wipe_db(db_psql: TypeDAL) -> TypeDAL:
    """Wipe every user-created schema in the database, then yield the DAL."""
    _wipe_all_schemas()
    return db_psql


@pytest.fixture()
def run_migrations(db_psql: TypeDAL) -> TypeDAL:
    """Run pending edwh-migrate migrations via subprocess (does not wipe first)."""
    _run_migrate_subprocess()
    return db_psql


@pytest.fixture(scope="module")
def wipe_db_per_file() -> None:
    """Wipe the database once per test file."""
    _wipe_all_schemas()


@pytest.fixture(scope="module")
def run_migrations_per_file() -> None:
    """Run migrations once per test file (does not wipe first)."""
    _run_migrate_subprocess()


@pytest.fixture(scope="module")
def migrated_db_per_file(wipe_db_per_file: None, run_migrations_per_file: None) -> None:
    """Wipe and migrate once per test file."""


@pytest.fixture(scope="module")
def db_per_file(migrated_db_per_file: None) -> t.Iterator[TypeDAL]:
    """Module-scoped TypeDAL instance with shared tables defined."""
    assert migrated_db_per_file is None

    with database_context() as database:
        yield database


def _pg_env() -> tuple[dict[str, str], dict[str, str]]:
    """Return ``(pg_connection_dict, subprocess_env_with_password)`` for pg_dump/pg_restore."""
    pg = _parse_postgres_uri(os.environ.get("POSTGRES_URI", ""))
    env = {**os.environ, "PGPASSWORD": pg["password"]}
    return pg, env


def _pg_dump_args(pg: dict[str, str], snapshot_dir: Path) -> list[str]:
    return [
        "pg_dump",
        "-F",
        "d",
        "-j",
        "4",
        "-h",
        pg["host"],
        "-p",
        pg["port"],
        "-U",
        pg["user"],
        "-d",
        pg["dbname"],
        "-f",
        str(snapshot_dir),
    ]


def _pg_restore_args(pg: dict[str, str], snapshot_dir: Path) -> list[str]:
    return [
        "pg_restore",
        "--exit-on-error",
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-privileges",
        "-h",
        pg["host"],
        "-p",
        pg["port"],
        "-U",
        pg["user"],
        "-d",
        pg["dbname"],
        str(snapshot_dir),
    ]


def _dump_or_raise(snapshot_dir: Path, snapshot_name: str, label: str) -> None:
    """Run pg_dump into *snapshot_dir*, or clean up and raise."""
    pg, env = _pg_env()
    result = subprocess.run(
        _pg_dump_args(pg, snapshot_dir),
        env=env,
        capture_output=True,
    )
    if result.returncode != 0:
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        raise RuntimeError(
            f"pg_dump failed for {label} snapshot {snapshot_name}:\n{result.stderr.decode(errors='replace')}"
        )


def _restore_snapshot(snapshot_dir: Path, snapshot_name: str, warning_prefix: str) -> None:
    """Wipe all schemas, restore from *snapshot_dir*, then remove it. Warns instead of raising."""
    _wipe_all_schemas()
    pg, env = _pg_env()
    restore_result = subprocess.run(
        _pg_restore_args(pg, snapshot_dir),
        env=env,
        capture_output=True,
    )
    shutil.rmtree(snapshot_dir, ignore_errors=True)
    if restore_result.returncode != 0:
        stderr = restore_result.stderr.decode(errors="replace")
        warnings.warn(
            f"{warning_prefix} teardown: pg_restore failed:\n{stderr}",
            RuntimeWarning,
            stacklevel=1,
        )


def _snapshot_lifecycle(label: str, warning_prefix: str) -> t.Iterator[str]:
    """Shared generator: dump → yield name → wipe + restore + cleanup."""
    suffix = _random_snapshot_suffix()
    snapshot_name = f"testing_{suffix}"
    snapshot_dir = SNAPSHOTS_DIR / snapshot_name
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    _dump_or_raise(snapshot_dir, snapshot_name, label)

    try:
        yield snapshot_name
    finally:
        _restore_snapshot(snapshot_dir, snapshot_name, warning_prefix)


@pytest.fixture(scope="module")
def snapshot_session_per_file() -> t.Iterator[str]:
    """Module-scoped snapshot: pg_dump before the first test in a file, restore after the last."""
    yield from _snapshot_lifecycle("module", "snapshot_session_per_file")


@pytest.fixture(scope="session")
def snapshot_session() -> t.Iterator[str]:
    """Session-scoped snapshot: pg_dump before tests, restore after teardown."""
    yield from _snapshot_lifecycle("session", "snapshot_session")


@pytest.fixture()
def snapshot_name() -> str:
    """Default snapshot name used by ``restored_db``. Override in a local conftest to change."""
    return DEFAULT_SNAPSHOT_NAME


@pytest.fixture()
def restored_db(wipe_db: TypeDAL, snapshot_name: str) -> TypeDAL:
    """Restore a pg_dump directory snapshot, then apply pending migrations.

    Override *snapshot_name* by defining your own fixture of the same name
    in a lower-level conftest.
    """
    snapshot_dir = SNAPSHOTS_DIR / snapshot_name
    if not snapshot_dir.is_dir():
        raise FileNotFoundError(f"snapshot directory not found: {snapshot_dir}")

    if not any(snapshot_dir.iterdir()):
        print(f"[restored_db] skipping restore of {snapshot_dir} because it's empty")
    else:
        _run_pg_restore(snapshot_dir)

    _run_migrate_subprocess()
    return wipe_db


@pytest.fixture()
def migrated_db(wipe_db: TypeDAL, run_migrations: TypeDAL) -> TypeDAL:
    """Wipe the database, then run all pending migrations."""
    return run_migrations
