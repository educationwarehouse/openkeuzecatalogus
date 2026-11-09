"""Integration coverage for location-scoped bulk user imports."""

import json
import typing as t
import uuid
from pathlib import Path

import pytest
from typedal import TypeDAL

from shared_code.data_model import AuthUser, DecisionTeam
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.auth.bulk_user_import import (
    CSV_HEADERS,
    apply_bulk_user_import,
    validate_bulk_user_import,
)
from shared_code.modules.auth.module import AuthSupportBackend
from shared_code.modules.decision_processes import DecisionProcessBackend
from shared_code.services.mail import MockMailer

LOCATION_GID = "db1e5f11-b1d0-4ca2-b350-57e089fe159d"


def _auth_support_backend(db: TypeDAL, inbox_path: Path) -> AuthSupportBackend:
    """Build the auth support backend with a real database and fake mail delivery."""
    auth_adapter = AuthAdapter.for_service("pytest.bulk-user-import")
    return AuthSupportBackend.with_injected(
        db=db,
        auth_adapter=auth_adapter,
        mailer=MockMailer(inbox_path=inbox_path),
    )


def _create_teams(db: TypeDAL, auth_adapter: AuthAdapter, *names: str) -> tuple[DecisionTeam, ...]:
    """Create registered teams in the seeded location."""
    backend = DecisionProcessBackend.with_injected(
        db=db,
        auth_adapter=auth_adapter,
    )
    return tuple(backend.create_team(LOCATION_GID, name) for name in names)


@pytest.fixture()
def team_backend(
    db_per_file: TypeDAL,
    admin_user: AuthUser,
    auth_adapter_factory: t.Callable[..., AuthAdapter],
) -> DecisionProcessBackend:
    """Create registered teams through the normal admin-authorised flow."""
    return DecisionProcessBackend.with_injected(
        db=db_per_file,
        auth_adapter=auth_adapter_factory(admin_user),
    )


@pytest.fixture()
def team_factory(team_backend: DecisionProcessBackend) -> t.Callable[..., tuple[DecisionTeam, ...]]:
    """Create registered teams through the normal admin-authorised flow."""
    return lambda *names: tuple(team_backend.create_team(LOCATION_GID, name) for name in names)


def _csv(*rows: str, headers: tuple[str, ...] = CSV_HEADERS) -> bytes:
    """Build an UTF-8 CSV fixture with the public import headers."""
    return ("\ufeff" + ",".join(headers) + "\n" + "\n".join(rows) + "\n").encode()


def _unique_email(prefix: str) -> str:
    """Return a test email that cannot collide with retained RBAC identities."""
    return f"{prefix}-{uuid.uuid4().hex}@example.test"


def test_bulk_user_import_creates_user_assigns_all_teams_and_sends_invite(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    tmp_path: Path,
    team_factory: t.Callable[..., tuple[DecisionTeam, ...]],
    team_backend: DecisionProcessBackend,
) -> None:
    """A valid row creates one identity, all requested memberships, and one invitation."""
    assert migrated_db_per_file is None
    inbox_path = tmp_path / "invites.jsonl"
    backend = _auth_support_backend(db_per_file, inbox_path)
    dutch, english = team_factory("Nederlands", "Engels")
    email = _unique_email("ada")

    plan, errors = validate_bulk_user_import(
        _csv(f"Ada,Lovelace,{email},Nederlands;Engels"),
        LOCATION_GID,
        backend,
    )

    assert errors == []
    assert plan is not None
    result = apply_bulk_user_import(
        plan,
        auth_support=backend,
        send_invitations=True,
        login_url="https://example.test/auth/login",
        decision_processes=team_backend,
    )

    identity = backend.auth.raw_rbac.get_user(email)
    assert identity is not None
    assert backend.has_direct_membership(identity["object_id"], dutch.gid)
    assert backend.has_direct_membership(identity["object_id"], english.gid)
    assert result.created_users == 1
    assert result.granted_memberships == 2
    assert result.invited_users == 1
    assert result.failed_invitations == 0
    assert len([json.loads(line) for line in inbox_path.read_text().splitlines()]) == 1


def test_bulk_user_import_grants_only_missing_membership_to_existing_user(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    tmp_path: Path,
    team_factory: t.Callable[..., tuple[DecisionTeam, ...]],
    team_backend: DecisionProcessBackend,
) -> None:
    """An existing user receives only the missing requested direct team membership."""
    assert migrated_db_per_file is None
    backend = _auth_support_backend(db_per_file, tmp_path / "invites.jsonl")
    dutch, english = team_factory("Nederlands", "Engels")
    email = _unique_email("ada")
    existing = backend.create_invited_identity(email, "Ada", "Lovelace")
    backend.grant_invited_membership(existing["subject_id"], dutch.gid)

    plan, errors = validate_bulk_user_import(
        _csv(f"Ada,Lovelace,{email},Nederlands;Engels"),
        LOCATION_GID,
        backend,
    )

    assert errors == []
    assert plan is not None
    assert plan.rows[0].existing_candidate["subject_id"] == existing["subject_id"]
    result = apply_bulk_user_import(
        plan,
        auth_support=backend,
        send_invitations=False,
        login_url="https://example.test/auth/login",
        decision_processes=team_backend,
    )

    assert backend.has_direct_membership(existing["subject_id"], english.gid)
    assert result.created_users == 0
    assert result.updated_users == 1
    assert result.granted_memberships == 1
    assert result.invited_users == 0


def test_bulk_user_import_rejects_invalid_file_without_creating_users(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    tmp_path: Path,
    team_factory: t.Callable[..., tuple[DecisionTeam, ...]],
) -> None:
    """One invalid row rejects the complete file before any identity is created."""
    assert migrated_db_per_file is None
    backend = _auth_support_backend(db_per_file, tmp_path / "invites.jsonl")
    team_factory("Nederlands")
    valid_email = _unique_email("ada")
    invalid_email = _unique_email("grace")

    plan, errors = validate_bulk_user_import(
        _csv(
            f"Ada,Lovelace,{valid_email},Nederlands",
            f"Grace,Hopper,{invalid_email},Onbekend",
        ),
        LOCATION_GID,
        backend,
    )

    assert plan is None
    assert errors == [{"row_number": 3, "message": "onbekende vakgroep(en) binnen deze vestiging: Onbekend"}]
    assert backend.auth.raw_rbac.get_user(valid_email) is None
    assert backend.auth.raw_rbac.get_user(invalid_email) is None


def test_bulk_user_import_can_create_unknown_teams_when_requested(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    tmp_path: Path,
    team_backend: DecisionProcessBackend,
) -> None:
    """The opt-in creates missing teams before assigning the imported user."""
    assert migrated_db_per_file is None
    backend = _auth_support_backend(db_per_file, tmp_path / "invites.jsonl")
    email = _unique_email("ada")

    plan, errors = validate_bulk_user_import(
        _csv(f"Ada,Lovelace,{email},Vakgroep Nederlands;Vakgroep Engels"),
        LOCATION_GID,
        backend,
        create_missing_teams=True,
    )

    assert errors == []
    assert plan is not None
    assert plan.missing_team_names == ("Vakgroep Nederlands", "Vakgroep Engels")
    result = apply_bulk_user_import(
        plan,
        auth_support=backend,
        send_invitations=False,
        login_url="https://example.test/auth/login",
        decision_processes=team_backend,
    )

    teams = {
        team.name: team for team in DecisionTeam.where(DecisionTeam.location_gid == LOCATION_GID).select().collect()
    }
    identity = backend.auth.raw_rbac.get_user(email)
    assert identity is not None
    assert backend.has_direct_membership(identity["object_id"], teams["Vakgroep Nederlands"].gid)
    assert backend.has_direct_membership(identity["object_id"], teams["Vakgroep Engels"].gid)
    assert result.created_users == 1


def test_bulk_user_import_rejects_missing_values_and_invalid_email(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    tmp_path: Path,
    team_factory: t.Callable[..., tuple[DecisionTeam, ...]],
) -> None:
    """Pydantic field validation and the shared email rules reject malformed rows."""
    assert migrated_db_per_file is None
    backend = _auth_support_backend(db_per_file, tmp_path / "invites.jsonl")
    team_factory("Nederlands")

    plan, errors = validate_bulk_user_import(
        _csv(
            ",Lovelace,ada@example.test,Nederlands",
            "Grace,Hopper,geen-e-mailadres,Nederlands",
        ),
        LOCATION_GID,
        backend,
    )

    assert plan is None
    assert {error["row_number"] for error in errors} == {2, 3}


def test_bulk_user_import_rejects_bad_headers_duplicate_email_and_existing_memberships(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    tmp_path: Path,
    team_factory: t.Callable[..., tuple[DecisionTeam, ...]],
) -> None:
    """Public CSV structure and duplicate or no-op rows are rejected with precise errors."""
    assert migrated_db_per_file is None
    backend = _auth_support_backend(db_per_file, tmp_path / "invites.jsonl")
    team = team_factory("Nederlands")[0]
    email = _unique_email("ada")
    existing = backend.create_invited_identity(email, "Ada", "Lovelace")
    backend.grant_invited_membership(existing["subject_id"], team.gid)

    header_plan, header_errors = validate_bulk_user_import(
        _csv(f"Ada,Lovelace,{email},Nederlands", headers=("email",)),
        LOCATION_GID,
        backend,
    )
    membership_plan, membership_errors = validate_bulk_user_import(
        _csv(f"Ada,Lovelace,{email},Nederlands"),
        LOCATION_GID,
        backend,
    )
    duplicate_email = _unique_email("grace")
    duplicate_plan, duplicate_errors = validate_bulk_user_import(
        _csv(
            f"Grace,Hopper,{duplicate_email},Nederlands",
            f"Grace,Hopper,{duplicate_email},Nederlands",
        ),
        LOCATION_GID,
        backend,
    )

    assert header_plan is None
    assert header_errors[0]["row_number"] is None
    assert membership_plan is None
    assert membership_errors == [
        {"row_number": 2, "message": "gebruiker heeft al toegang tot alle opgegeven vakgroepen"}
    ]
    assert duplicate_plan is None
    assert duplicate_errors == [{"row_number": 3, "message": "e-mailadres komt meerdere keren in het bestand voor"}]


class FailingMailer(MockMailer):
    """Mail test double that simulates an unavailable delivery service."""

    def send(self, *args: object, **kwargs: object) -> bool:
        raise OSError("mail service unavailable")


def test_bulk_user_import_reports_mail_failure_without_rolling_back(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    tmp_path: Path,
    team_factory: t.Callable[..., tuple[DecisionTeam, ...]],
    team_backend: DecisionProcessBackend,
) -> None:
    """Delivery failure is reported after the database import remains committed."""
    assert migrated_db_per_file is None
    auth_adapter = AuthAdapter.for_service("pytest.bulk-user-import-failing-mail")
    backend = AuthSupportBackend.with_injected(
        db=db_per_file,
        auth_adapter=auth_adapter,
        mailer=FailingMailer(inbox_path=tmp_path / "invites.jsonl"),
    )
    team = team_factory("Nederlands")[0]
    email = _unique_email("ada")
    plan, errors = validate_bulk_user_import(
        _csv(f"Ada,Lovelace,{email},Nederlands"),
        LOCATION_GID,
        backend,
    )

    assert errors == []
    assert plan is not None
    result = apply_bulk_user_import(
        plan,
        auth_support=backend,
        send_invitations=True,
        login_url="https://example.test/auth/login",
        decision_processes=team_backend,
    )

    identity = backend.auth.raw_rbac.get_user(email)
    assert identity is not None
    assert backend.has_direct_membership(identity["object_id"], team.gid)
    assert result.failed_invitations == 1
