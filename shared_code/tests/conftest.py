"""Shared pytest fixtures for shared_code tests."""

import os
import secrets
import shutil
import string
import subprocess
import typing as t
import warnings
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest
from edwh_auth_rbac import AuthRbac

from shared_code.data_model import (
    AuthUser,
    DynamicFilter,
    DynamicSort,
    MethodEd,
    ProductEd,
    Supplier,
    SupplierEd,
    VisionEd,
)
from shared_code.data_model.constants import ROLE_ADMIN, ROLE_BOARD, ROLE_LOCATION, ROLE_ORGANISATION, ROLE_SCHOOL, ROLE_SUPPLIER, ROLE_USER
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.auth.contract import AuthActor, AuthContext
from shared_code.data_model.setup import define_tables
from shared_code.infra.database import database_context, DatabaseContext as TypeDAL
from shared_code.services.applog import Applogger


DEFAULT_SNAPSHOT_NAME = "testing.snapshot"
MOCK_INBOX_PATH = Path(os.environ.get("SMTP_FAKE_INBOX_PATH", "/shared_cache/mail/mock_inbox.jsonl"))

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
    if not os.environ.get("POSTGRES_URI"):
        raise RuntimeError("POSTGRES_URI is required for shared_code tests.")

    database = TypeDAL.with_injected(auth_adapter=AuthAdapter.for_service("pytest.db_psql"))
    try:
        yield database
    finally:
        database.close()


@pytest.fixture(autouse=True)
def clear_fake_mail_inbox() -> None:
    """Prevent cross-test interference from the shared fake SMTP inbox file."""
    MOCK_INBOX_PATH.parent.mkdir(parents=True, exist_ok=True)
    MOCK_INBOX_PATH.unlink(missing_ok=True)
    MOCK_INBOX_PATH.touch()


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

    with database_context("pytest.db_per_file") as database:
        yield database


def _unique_email(prefix: str, domain: str = "example.test") -> str:
    """Return a unique email address for test users."""
    return f"{prefix}-{uuid.uuid4().hex}@{domain}"


def _unique_slug(prefix: str) -> str:
    """Return a unique slug that fits the dynamic config table limits."""
    suffix = uuid.uuid4().hex[:8]
    trimmed_prefix = prefix[:31]
    return f"{trimmed_prefix}-{suffix}"


def _seed_rbac_roles(db: TypeDAL) -> AuthRbac:
    """Create the RBAC model and base roles needed by shared user fixtures."""
    rbac = AuthRbac(db)
    rbac.define_model(allowed_types=["user", "group", "item"], redefine=True, migrate=False)
    rbac.add_group(ROLE_USER, "Users", [], allow_existing=True)
    organisation = rbac.add_group(ROLE_ORGANISATION, "Organisaties", [ROLE_USER], allow_existing=True)
    rbac.add_group(ROLE_BOARD, "Besturen", [organisation["object_id"]], allow_existing=True)
    rbac.add_group(ROLE_SCHOOL, "Scholen", [organisation["object_id"]], allow_existing=True)
    rbac.add_group(ROLE_LOCATION, "Vestigingen", [organisation["object_id"]], allow_existing=True)
    rbac.add_group(ROLE_SUPPLIER, "Suppliers", [], allow_existing=True)
    rbac.add_group(ROLE_ADMIN, "Admins", [], allow_existing=True)
    db.commit()
    return rbac


@pytest.fixture()
def seeded_rbac(db_per_file: TypeDAL) -> AuthRbac:
    """RBAC model with the shared user-role identities pre-seeded."""
    return _seed_rbac_roles(db_per_file)


def _build_auth_adapter(
    user: AuthUser,
    roles: t.Iterable[str] = (),
    permissions: t.Iterable[str] = (),
    grant_membership: t.Callable[[AuthContext, str, str], None] | None = None,
    check_membership: t.Callable[[AuthContext, str], bool] | None = None,
    check_permission: t.Callable[[AuthContext, str], bool] | None = None,
) -> AuthAdapter:
    """Create a user-scoped AuthAdapter for test fixtures."""
    role_set = set(roles)
    permission_set = set(permissions)
    actor = AuthActor(
        kind="user",
        id=str(user.gid),
        email=user.email,
        name=user.full_name,
    )
    return AuthAdapter(
        get_actor=lambda: actor,
        get_roles=lambda _ctx: set(role_set),
        get_permissions=lambda _ctx: set(permission_set),
        grant_membership=grant_membership,
        check_membership=check_membership,
        check_permission=check_permission,
    )


@pytest.fixture()
def auth_user_factory(
    seeded_rbac: AuthRbac,
) -> t.Iterator[t.Callable[..., AuthUser]]:
    """Build and tear down auth users created during a test."""
    created_user_ids: list[int] = []

    def create_user(
        prefix: str = "user",
        domain: str = "example.test",
        first_name: str = "Test",
        last_name: str = "User",
        password: str = "ValidPass123!",  # noqa: S106 - test credential
        roles: t.Iterable[str] = (),
    ) -> AuthUser:
        email = _unique_email(prefix, domain)
        row, errors = AuthUser.validate_and_insert(
            email=email,
            first_name=first_name,
            last_name=last_name,
            password=password,
        )
        assert row, errors

        user = AuthUser(row["id"])
        assert user is not None

        for role in roles:
            seeded_rbac.add_membership(str(user.gid), str(role))

        AuthUser._db.commit()
        created_user_ids.append(user.id)
        return user

    yield create_user

    for user_id in reversed(created_user_ids):
        user = AuthUser(user_id)
        if user:
            user.delete_record()
    AuthUser._db.commit()


@pytest.fixture()
def normal_user(auth_user_factory: t.Callable[..., AuthUser]) -> AuthUser:
    """Create a baseline user with only the default user membership."""
    return auth_user_factory(prefix="normal")


@pytest.fixture()
def admin_user(auth_user_factory: t.Callable[..., AuthUser]) -> AuthUser:
    """Create a user with the admin membership."""
    return auth_user_factory(prefix="admin", roles=[ROLE_ADMIN])


@pytest.fixture()
def auth_adapter_factory(
    seeded_rbac: AuthRbac,
) -> t.Callable[..., AuthAdapter]:
    """Create a reusable AuthAdapter factory for user-scoped tests."""

    def create_adapter(
        user: AuthUser,
        roles: t.Iterable[str] = (),
        permissions: t.Iterable[str] = (),
        grant_membership: t.Callable[[AuthContext, str, str], None] | None = None,
        check_membership: t.Callable[[AuthContext, str], bool] | None = None,
        check_permission: t.Callable[[AuthContext, str], bool] | None = None,
    ) -> AuthAdapter:
        subject = str(user.gid)
        default_grant = lambda _ctx, current_subject, role: seeded_rbac.add_membership(current_subject, role)
        default_check = lambda _ctx, role: seeded_rbac.has_membership(subject, role)
        return _build_auth_adapter(
            user,
            roles=roles,
            permissions=permissions,
            grant_membership=grant_membership or default_grant,
            check_membership=check_membership or default_check,
            check_permission=check_permission,
        )

    return create_adapter

@pytest.fixture()
def supplier_factory(db_per_file: TypeDAL) -> t.Iterator[t.Callable[..., Supplier]]:
    """Build and tear down supplier rows created during a test."""
    created_supplier_ids: list[int] = []

    def create_supplier(
        name: str,
        email_domains: list[str],
        endpoint_type: str = "none",
        allow_existing: bool = True,
    ) -> Supplier:
        primary_domain = email_domains[0]

        if allow_existing and (existing := Supplier.where(Supplier.email_domains.contains(primary_domain)).first()):
            return existing

        row = SupplierEd.insert(
            name=name,
            email_domains=email_domains,
            endpoint_type=endpoint_type,
        )
        assert row is not None
        db_per_file.commit()
        created_supplier_ids.append(row.id)
        return t.cast(Supplier, row)

    yield create_supplier

    for supplier_id in reversed(created_supplier_ids):
        supplier = Supplier(supplier_id)
        if supplier:
            supplier.delete_record()
    db_per_file.commit()


@pytest.fixture()
def supplier(supplier_factory: t.Callable[..., Supplier]) -> Supplier:
    """Create a generic supplier row for membership-oriented tests."""
    return supplier_factory(
        name="Supplier Test",
        email_domains=["supplier.example.test"],
    )


@pytest.fixture()
def method_factory(db_per_file: TypeDAL) -> t.Iterator[t.Callable[..., MethodEd]]:
    """Build and tear down method rows created during one test."""
    created_method_ids: list[int] = []

    def create_method(
        *,
        supplier_gid: str,
        olid: str,
        name: str,
        available: str = "leverbaar",
        guide_price: float | None = None,
    ) -> MethodEd:
        row = MethodEd.insert(
            supplier_gid=supplier_gid,
            olid=olid,
            name=name,
            available=available,
            guide_price=guide_price,
        )
        assert row is not None
        db_per_file.commit()
        created_method_ids.append(row.id)
        return row

    yield create_method

    for method_id in reversed(created_method_ids):
        row = MethodEd(method_id)
        if row:
            row.delete_record()
    db_per_file.commit()


@pytest.fixture()
def product_factory(db_per_file: TypeDAL) -> t.Iterator[t.Callable[..., ProductEd]]:
    """Build and tear down product rows created during one test."""
    created_product_ids: list[int] = []

    def create_product(
        *,
        supplier_gid: str,
        method_gid: str,
        olid: str,
        name: str,
        levels: list[str] | None = None,
        available: str = "leverbaar",
        composition: str = "single",
        description: str | None = None,
        recommended_price: float | None = None,
        tto: bool | None = None,
    ) -> ProductEd:
        row = ProductEd.insert(
            supplier_gid=supplier_gid,
            method_gid=method_gid,
            olid=olid,
            name=name,
            levels=levels or [],
            available=available,
            composition=composition,
            description=description,
            recommended_price=recommended_price,
            tto=tto,
        )
        assert row is not None
        db_per_file.commit()
        created_product_ids.append(row.id)
        return row

    yield create_product

    for product_id in reversed(created_product_ids):
        row = ProductEd(product_id)
        if row:
            row.delete_record()
    db_per_file.commit()


@pytest.fixture()
def vision_factory(db_per_file: TypeDAL) -> t.Iterator[t.Callable[..., VisionEd]]:
    """Build and tear down vision rows created during one test."""
    created_vision_ids: list[int] = []

    def create_vision(*, olid: str, onderwijskwaliteit: str, visie: str) -> VisionEd:
        row = VisionEd.insert(
            olid=olid,
            onderwijskwaliteit=onderwijskwaliteit,
            visie=visie,
        )
        assert row is not None
        db_per_file.commit()
        created_vision_ids.append(row.id)
        return row

    yield create_vision

    for vision_id in reversed(created_vision_ids):
        row = VisionEd(vision_id)
        if row:
            row.delete_record()
    db_per_file.commit()


@pytest.fixture()
def dynamic_filter_factory(db_per_file: TypeDAL) -> t.Iterator[t.Callable[..., DynamicFilter]]:
    """Build and tear down dynamic filter rows created during one test."""
    created_filter_ids: list[int] = []

    def create_filter(
        *,
        slug: str,
        label: str,
        filter_kind: str,
        applies_to: str,
        sort_order: int,
        field_name: str | None = None,
        match_mode: str = "contains",
        handler_key: str | None = None,
        widget_kind: str | None = None,
    ) -> DynamicFilter:
        row = DynamicFilter.insert(
            slug=_unique_slug(slug),
            label=label,
            filter_kind=filter_kind,
            field_name=field_name,
            match_mode=match_mode,
            applies_to=applies_to,
            handler_key=handler_key,
            widget_kind=widget_kind,
            is_active=True,
            sort_order=sort_order,
        )
        assert row is not None
        db_per_file.commit()
        created_filter_ids.append(row.id)
        return row

    yield create_filter

    for filter_id in reversed(created_filter_ids):
        row = DynamicFilter(filter_id)
        if row:
            row.delete_record()
    db_per_file.commit()


@pytest.fixture()
def dynamic_sort_factory(db_per_file: TypeDAL) -> t.Iterator[t.Callable[..., DynamicSort]]:
    """Build and tear down dynamic sort rows created during one test."""
    created_sort_ids: list[int] = []

    def create_sort(
        *,
        slug: str,
        label: str,
        applies_to: str,
        order_expression: str,
        sort_order: int,
        is_default: bool = False,
    ) -> DynamicSort:
        row = DynamicSort.insert(
            slug=_unique_slug(slug),
            label=label,
            applies_to=applies_to,
            order_expression=order_expression,
            is_default=is_default,
            is_active=True,
            sort_order=sort_order,
        )
        assert row is not None
        db_per_file.commit()
        created_sort_ids.append(row.id)
        return row

    yield create_sort

    for sort_id in reversed(created_sort_ids):
        row = DynamicSort(sort_id)
        if row:
            row.delete_record()
    db_per_file.commit()


@pytest.fixture()
def supplier_user(
    auth_user_factory: t.Callable[..., AuthUser],
    supplier: Supplier,
) -> AuthUser:
    """Create a user that belongs to the supplier RBAC identity."""
    return auth_user_factory(
        prefix="supplier",
        domain=(supplier.email_domains[0] if supplier.email_domains else "example.test"),
        roles=[str(supplier.gid)],
    )


@pytest.fixture()
def supplier_adapter(
    auth_adapter_factory: t.Callable[..., AuthAdapter],
    supplier_user: AuthUser,
    supplier: Supplier,
) -> AuthAdapter:
    """Create an adapter for a user that belongs to a supplier."""
    return auth_adapter_factory(supplier_user, roles=[ROLE_USER, str(supplier.gid)])


@pytest.fixture()
def education_warehouse_supplier(
    db_per_file: TypeDAL,
    seeded_rbac: AuthRbac,
) -> Supplier:
    """Return the Education Warehouse supplier, creating it once if needed."""
    if existing := Supplier.where(Supplier.email_domains.contains("educationwarehouse.nl")).first():
        supplier = t.cast(Supplier, existing)
    else:
        supplier = t.cast(
            Supplier,
            SupplierEd.insert(
                name="Education Warehouse",
                email_domains=["educationwarehouse.nl"],
                endpoint_type="none",
            ),
        )
        db_per_file.commit()

    if not supplier:
        raise RuntimeError("Failed to create the Education Warehouse supplier")

    if not seeded_rbac.has_membership(str(supplier.gid), ROLE_ADMIN):
        seeded_rbac.add_membership(str(supplier.gid), ROLE_ADMIN)
        db_per_file.commit()

    return supplier


@pytest.fixture()
def education_warehouse_supplier_user(
    auth_user_factory: t.Callable[..., AuthUser],
    education_warehouse_supplier: Supplier,
) -> AuthUser:
    """Create a user that belongs to the Education Warehouse supplier."""
    return auth_user_factory(
        prefix="education-warehouse",
        domain=(education_warehouse_supplier.email_domains[0] if education_warehouse_supplier.email_domains else "example.test"),
        roles=[str(education_warehouse_supplier.gid)],
    )


@pytest.fixture()
def education_warehouse_admin_user(
    auth_user_factory: t.Callable[..., AuthUser],
    education_warehouse_supplier: Supplier,
) -> AuthUser:
    """Create a user that receives admin access through the supplier hierarchy."""
    return auth_user_factory(
        prefix="education-warehouse",
        domain=(education_warehouse_supplier.email_domains[0] if education_warehouse_supplier.email_domains else "example.test"),
        roles=[str(education_warehouse_supplier.gid)],
    )


@pytest.fixture()
def education_warehouse_supplier_adapter(
    auth_adapter_factory: t.Callable[..., AuthAdapter],
    education_warehouse_supplier_user: AuthUser,
    education_warehouse_supplier: Supplier,
) -> AuthAdapter:
    """Create an adapter for an Education Warehouse supplier user."""
    return auth_adapter_factory(
        education_warehouse_supplier_user,
        roles=[ROLE_USER, str(education_warehouse_supplier.gid)],
    )


@pytest.fixture()
def education_warehouse_admin_adapter(
    auth_adapter_factory: t.Callable[..., AuthAdapter],
    education_warehouse_admin_user: AuthUser,
    education_warehouse_supplier: Supplier,
) -> AuthAdapter:
    """Create an adapter for a user who inherits admin through the supplier chain."""
    return auth_adapter_factory(
        education_warehouse_admin_user,
        roles=[ROLE_USER, str(education_warehouse_supplier.gid), ROLE_ADMIN],
    )



def _pg_env() -> tuple[dict[str, str], dict[str, str]]:
    """Return `(pg_connection_dict, subprocess_env_with_password)` for pg_dump/pg_restore."""
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
    """Default snapshot name used by `restored_db`. Override in a local conftest to change."""
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
