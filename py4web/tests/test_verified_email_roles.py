"""Tests for supplier-backed role grants during verification and login."""

import typing as t
import uuid
from pathlib import Path

import pytest
from common.models import auth as app_auth
from edwh_auth_rbac import AuthRbac

from shared_code.data_model import Supplier
from shared_code.data_model.constants import ROLE_ADMIN, ROLE_SUPPLIER
from shared_code.data_model.tables import AuthUser, SupplierEd

rbac = app_auth.auth_context.raw_rbac


def _unique_email(domain: str) -> str:
    return f"verified-{uuid.uuid4().hex}@{domain}"


@pytest.fixture()
def verified_email_role_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep applog writes local and ensure base RBAC roles exist."""
    monkeypatch.setenv("APPLOG_FAKE", "1")
    monkeypatch.setenv("APPLOG_PATH", str(tmp_path / "applog.jsonl"))

    rbac = AuthRbac(AuthUser._db)
    rbac.define_model(allowed_types=["user", "group", "item"], redefine=True, migrate=False)
    rbac.add_group(ROLE_SUPPLIER, "Suppliers", [], allow_existing=True)
    rbac.add_group(ROLE_ADMIN, "Admins", [], allow_existing=True)
    AuthUser._db.commit()


@pytest.fixture()
def created_users() -> list[str]:
    """Track created users and remove them after each test."""
    emails: list[str] = []
    yield emails

    for email in reversed(emails):
        user = AuthUser(email=email)
        if user:
            user.delete_record()
    AuthUser._db.commit()


def _create_user(email: str) -> AuthUser:
    row, errors = AuthUser.validate_and_insert(
        email=email,
        first_name="Verified",
        last_name="User",
        password="ValidPass123!",  # noqa: S106 - test credential
    )
    assert row, errors

    user = AuthUser(row["id"])
    assert user is not None
    return user


def _get_or_create_supplier(domain: str, name: str | None = None) -> Supplier:
    if existing := Supplier.where(Supplier.email_domains.contains(domain)).first():
        return existing

    supplier = SupplierEd.insert(
        name=name or f"Supplier {uuid.uuid4().hex[:8]}",
        email_domains=[domain],
        endpoint_type="none",
    )
    AuthUser._db.commit()
    return t.cast(Supplier, supplier)


def test_verify_email_grants_supplier_membership_for_matching_domain(
    verified_email_role_environment: None,
    created_users: list[str],
) -> None:
    """Verification should add the user to the matching supplier group."""
    assert verified_email_role_environment is None

    supplier = _get_or_create_supplier("educationwarehouse.nl", name="Education Warehouse")
    user = _create_user(_unique_email("educationwarehouse.nl"))
    created_users.append(user.email)

    app_auth.grant_roles_after_email_verification(None, user)

    assert rbac.has_membership(str(user.gid), str(supplier.gid))


def test_verify_email_inherits_admin_via_supplier_group(
    verified_email_role_environment: None,
    created_users: list[str],
) -> None:
    """Verification should inherit admin when the supplier group inherits admin."""
    assert verified_email_role_environment is None

    supplier = _get_or_create_supplier("sivon.nl", name="SIVON")
    app_auth.auth_context.add_membership(str(supplier.gid), ROLE_ADMIN)
    AuthUser._db.commit()

    user = _create_user(_unique_email("sivon.nl"))
    created_users.append(user.email)

    app_auth.grant_roles_after_email_verification(None, user)

    assert rbac.has_membership(str(user.gid), str(supplier.gid))
    assert rbac.has_membership(str(user.gid), ROLE_ADMIN)
    # note: auth.store_user_in_session can't properly be tested here since no Session
