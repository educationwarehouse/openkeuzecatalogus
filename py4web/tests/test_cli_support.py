"""Tests for the admin CLI support helpers."""

import json
import typing as t
import uuid
from pathlib import Path

import pytest
from apps.admin.models import cli_support
from common.models import db
from edwh_auth_rbac import AuthRbac

from py4web import HTTP
from shared_code.data_model.constants import ROLE_ADMIN, ROLE_USER


def _ensure_role_identity(role: str) -> None:
    """Seed a role identity row if the database does not already have it."""
    if db.identity(email=role):
        return

    AuthRbac(db).add_group(role, role, [])
    db.commit()


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}@example.test"


@pytest.fixture()
def admin_cli_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep applog writes local and make sure the default role identities exist."""
    monkeypatch.setenv("APPLOG_FAKE", "1")
    monkeypatch.setenv("APPLOG_PATH", str(tmp_path / "applog.jsonl"))

    _ensure_role_identity(ROLE_USER)
    _ensure_role_identity(ROLE_ADMIN)


@pytest.fixture()
def created_users() -> t.Iterator[list[str]]:
    """Track user emails created by a test and clean them up afterwards."""
    emails: list[str] = []
    yield emails

    for email in reversed(emails):
        user = cli_support._find_user(email)
        if user:
            cli_support.remove_user(email)


def test_normalize_role_handles_aliases_and_internal_names() -> None:
    """Role aliases should map to canonical internal role identifiers."""
    assert cli_support.normalize_role("admin") == ROLE_ADMIN
    assert cli_support.normalize_role(" user ") == ROLE_USER
    assert cli_support.normalize_role("support@internal") == "support@internal"


def test_add_user_and_list_users_round_trip(
    admin_cli_environment: None,
    created_users: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Creating users should persist role memberships and list cleanly."""
    assert admin_cli_environment is None

    admin_email = _unique_email("admin")
    plain_email = _unique_email("plain")

    admin_result = cli_support.add_user(
        email=f"  {admin_email.upper()}  ",
        first_name="  Jane  ",
        last_name="  Doe  ",
        password="ValidPass123!",  # noqa: S106 - insecure password allowed in tests
        roles=["admin"],
    )
    created_users.append(admin_result["email"])

    plain_result = cli_support.add_user(
        email=f"  {plain_email.upper()}  ",
        first_name="  Plain  ",
        last_name="  User  ",
        password="ValidPass123!",  # noqa: S106 - insecure password allowed in tests
    )
    created_users.append(plain_result["email"])
    capsys.readouterr()

    payload = cli_support.list_users()
    emitted = capsys.readouterr()

    assert json.loads(emitted.out.strip()) == payload

    users_by_email = {row["email"]: row for row in payload["users"]}

    admin_row = users_by_email[admin_result["email"]]
    assert admin_row["first_name"] == "Jane"
    assert admin_row["last_name"] == "Doe"
    assert admin_row["role_ids"] == [ROLE_ADMIN]

    plain_row = users_by_email[plain_result["email"]]
    assert plain_row["first_name"] == "Plain"
    assert plain_row["last_name"] == "User"
    assert plain_row["role_ids"] == []

    filtered = cli_support.list_users("admin")
    filtered_emails = {row["email"] for row in filtered["users"]}
    assert admin_result["email"] in filtered_emails
    assert plain_result["email"] not in filtered_emails


def test_grant_revoke_and_remove_user_manage_memberships(
    admin_cli_environment: None,
    created_users: list[str],
) -> None:
    """Role assignment helpers should update memberships in the live database."""
    assert admin_cli_environment is None

    email = _unique_email("member")
    result = cli_support.add_user(
        email=email,
        first_name="Member",
        last_name="User",
        password="ValidPass123!",  # noqa: S106 - insecure password allowed in tests
    )
    created_users.append(result["email"])

    cli_support.grant_role(result["email"], "admin")
    admin_rows = cli_support.list_users("admin")["users"]
    assert any(row["email"] == result["email"] for row in admin_rows)

    cli_support.revoke_role(result["email"], "admin")
    admin_rows = cli_support.list_users("admin")["users"]
    assert not any(row["email"] == result["email"] for row in admin_rows)

    cli_support.remove_user(result["email"])
    created_users.remove(result["email"])

    users = cli_support.list_users()["users"]
    assert not any(row["email"] == result["email"] for row in users)


def test_set_password_rejects_empty_password_and_accepts_valid_one(
    admin_cli_environment: None,
    created_users: list[str],
) -> None:
    """Password updates should enforce the empty-password guard and accept valid input."""
    assert admin_cli_environment is None

    email = _unique_email("password")
    result = cli_support.add_user(
        email=email,
        first_name="Pass",
        last_name="Word",
        password="ValidPass123!",  # noqa: S106 - insecure password allowed in tests
    )
    created_users.append(result["email"])

    with pytest.raises(HTTP, match="Password cannot be empty"):
        cli_support.set_password(result["email"], "   ")

    updated = cli_support.set_password(result["email"], "EvenBetterPass123!")
    assert updated == {"ok": True, "email": result["email"]}
