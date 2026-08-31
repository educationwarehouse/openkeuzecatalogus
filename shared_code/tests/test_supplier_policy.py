"""Tests for the supplier backend policy seam."""
import typing as t

from edwh_auth_rbac import AuthRbac
from typedal import TypeDAL

from shared_code.data_model import AuthUser, Supplier
from shared_code.data_model.constants import ROLE_ADMIN
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.auth.contract import AuthContext
from shared_code.modules.suppliers import SupplierBackend
from shared_code.modules.suppliers.policy import SupplierPolicy


def _make_backend(auth: AuthAdapter, db: TypeDAL) -> SupplierBackend:
    """Construct a supplier backend with endow injection."""
    return SupplierBackend.with_injected(
        db=db,
        auth_adapter=auth,
    )


def test_auth_context_for_service_builds_service_actor() -> None:
    """Service-scoped auth should expose the expected actor details."""
    ctx = AuthContext.for_service("supplier-sync")

    assert ctx.is_service()
    assert not ctx.is_user()
    assert not ctx.is_anonymous()
    assert ctx.id == "service:supplier-sync"
    assert ctx.get_email() == "supplier-sync@internal"
    assert ctx.actor.name == "supplier-sync"
    assert ctx.roles == []
    assert ctx.permissions == []


def test_supplier_policy_can_access_supplier_checks_admin_and_membership(
    db_psql: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    admin_user: AuthUser,
    auth_user_factory: t.Callable[..., AuthUser],
    auth_adapter_factory: t.Callable[..., AuthAdapter],
    seeded_rbac: AuthRbac,
) -> None:
    """Supplier access should accept admins and matching supplier memberships."""
    supplier = supplier_factory(name="Policy Supplier", email_domains=["policy.example.test"])

    admin_policy = SupplierPolicy.with_injected(
        db=db_psql,
        auth_adapter=auth_adapter_factory(admin_user, roles=[ROLE_ADMIN]),
    )
    member_user = auth_user_factory(prefix="member", domain="policy.example.test")
    seeded_rbac.add_membership(str(member_user.gid), str(supplier.gid))
    member_policy = SupplierPolicy.with_injected(
        db=db_psql,
        auth_adapter=auth_adapter_factory(member_user),
    )
    outsider_user = auth_user_factory(prefix="outsider", domain="policy.example.test")
    outsider_policy = SupplierPolicy.with_injected(
        db=db_psql,
        auth_adapter=auth_adapter_factory(outsider_user),
    )

    assert admin_policy.can_access_supplier(str(supplier.gid))
    assert member_policy.can_access_supplier(str(supplier.gid))
    assert not outsider_policy.can_access_supplier(str(supplier.gid))


def test_supplier_backend_grant_memberships_adds_matching_supplier_membership(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    education_warehouse_supplier: Supplier,
    education_warehouse_supplier_user: AuthUser,
    education_warehouse_supplier_adapter: AuthAdapter,
    seeded_rbac: AuthRbac,
) -> None:
    """Matching user emails should be linked to the corresponding supplier group."""
    assert migrated_db_per_file is None

    backend = _make_backend(education_warehouse_supplier_adapter, db_per_file)

    backend.grant_memberships(education_warehouse_supplier_user)
    db_per_file.commit()

    assert seeded_rbac.has_membership(str(education_warehouse_supplier_user.gid), str(education_warehouse_supplier.gid))


def test_education_warehouse_user_inherits_admin_via_supplier(
    education_warehouse_admin_user: AuthUser,
    education_warehouse_supplier: Supplier,
    seeded_rbac: AuthRbac,
) -> None:
    """Education Warehouse users should inherit admin from the supplier RBAC chain."""
    assert seeded_rbac.has_membership(str(education_warehouse_admin_user.gid), str(education_warehouse_supplier.gid))
    assert seeded_rbac.has_membership(str(education_warehouse_admin_user.gid), ROLE_ADMIN)


def test_supplier_backend_list_suppliers_returns_only_visible_rows_for_member(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    auth_user_factory: t.Callable[..., AuthUser],
    auth_adapter_factory: t.Callable[..., AuthAdapter],
) -> None:
    """Members should only see suppliers they belong to."""
    assert migrated_db_per_file is None

    visible_supplier = supplier_factory(name="Visible Supplier", email_domains=["visible.example.test"])
    hidden_supplier = supplier_factory(name="Hidden Supplier", email_domains=["hidden.example.test"])

    user = auth_user_factory(prefix="member", domain="visible.example.test")

    auth = auth_adapter_factory(user)
    backend = _make_backend(auth, db_per_file)

    backend.grant_memberships(user)
    db_per_file.commit()

    rows = backend.list_my_suppliers().collect()
    row_gids = {str(row.gid) for row in rows}

    assert row_gids == {str(visible_supplier.gid)}
    assert str(hidden_supplier.gid) not in row_gids


def test_supplier_member_has_read_write_access_to_own_supplier(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    auth_user_factory: t.Callable[..., AuthUser],
    auth_adapter_factory: t.Callable[..., AuthAdapter],
    seeded_rbac: AuthRbac,
) -> None:
    """Supplier members should have read and write RBAC access to their own supplier."""
    assert migrated_db_per_file is None

    supplier = supplier_factory(name="Writable Supplier", email_domains=["writable.example.test"])

    user = auth_user_factory(prefix="member", domain="writable.example.test")
    backend = _make_backend(auth_adapter_factory(user), db_per_file)

    backend.grant_memberships(user)
    db_per_file.commit()

    assert seeded_rbac.has_membership(str(user.gid), str(supplier.gid))
    assert seeded_rbac.has_permission(str(user.gid), str(supplier.gid), "read")
    assert seeded_rbac.has_permission(str(user.gid), str(supplier.gid), "write")


def test_supplier_backend_list_suppliers_returns_all_rows_for_admin(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    education_warehouse_admin_adapter: AuthAdapter,
    education_warehouse_admin_user: AuthUser,
    education_warehouse_supplier: Supplier,
    seeded_rbac: AuthRbac,
) -> None:
    """Admin access should be inherited through the supplier RBAC hierarchy."""
    assert migrated_db_per_file is None

    first_supplier = supplier_factory(name="Admin Visible One", email_domains=["admin-visible-1.example.test"])
    second_supplier = supplier_factory(name="Admin Visible Two", email_domains=["admin-visible-2.example.test"])

    backend = _make_backend(education_warehouse_admin_adapter, db_per_file)

    assert seeded_rbac.has_membership(str(education_warehouse_admin_user.gid), str(education_warehouse_supplier.gid))
    assert seeded_rbac.has_membership(str(education_warehouse_admin_user.gid), ROLE_ADMIN)

    rows = backend.list_my_suppliers().collect()
    row_gids = {str(row.gid) for row in rows}

    assert {str(first_supplier.gid), str(second_supplier.gid)}.issubset(row_gids), "missing expected supplier"
