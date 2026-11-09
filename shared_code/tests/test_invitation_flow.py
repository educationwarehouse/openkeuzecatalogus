"""Tests for shared membership invitation flow state handling."""

import uuid
from pathlib import Path

from edwh_auth_rbac import AuthRbac
from typedal import TypeDAL

from shared_code.modules.auth import AuthAdapter
from shared_code.modules.auth.invitation_flow import (
    invite_values,
    resolve_grant_state,
    resolve_invite_state,
    resolve_invite_step,
    resolve_lookup_state,
)
from shared_code.modules.auth.module import AuthSupportBackend
from shared_code.services.mail import MockMailer


def _make_auth_support_backend(db: TypeDAL, mailer: MockMailer | None = None) -> AuthSupportBackend:
    """Build the shared auth support backend for one test."""
    auth_adapter = AuthAdapter.for_service("pytest.invitation_flow")
    return AuthSupportBackend.with_injected(
        db=db,
        auth_adapter=auth_adapter,
        mailer=mailer or MockMailer.with_injected(auth_adapter=auth_adapter),
    )


def _create_membership_target(seeded_rbac: AuthRbac, db: TypeDAL, name: str) -> str:
    """Create one RBAC membership target and return its gid."""
    suffix = uuid.uuid4().hex
    membership = seeded_rbac.add_group(
        f"invite-target-{suffix}@internal",
        name,
        [],
        allow_existing=True,
    )
    db.commit()
    return str(membership["object_id"])


def test_invite_membership_grants_inherited_user_without_duplicate_email(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    seeded_rbac: AuthRbac,
    tmp_path: Path,
) -> None:
    """An inherited member receives a direct row, while only a new identity receives an email."""
    assert migrated_db_per_file is None
    inbox_path = tmp_path / "invites.jsonl"
    backend = _make_auth_support_backend(db_per_file, mailer=MockMailer(inbox_path=inbox_path))
    membership_gid = _create_membership_target(seeded_rbac, db_per_file, "Invite Membership")
    inherited_group = seeded_rbac.add_group(
        f"invite-inherited-{uuid.uuid4().hex}@internal",
        "Inherited invite group",
        [membership_gid],
        allow_existing=True,
    )
    inherited_email = f"invite-inherited-{uuid.uuid4().hex}@example.test"
    inherited = backend.create_invited_identity(inherited_email, "Inherited", "Member")
    backend.grant_invited_membership(inherited["subject_id"], str(inherited_group["object_id"]))

    assert backend.auth.has_subject_membership(inherited["subject_id"], membership_gid) is True
    assert backend.has_direct_membership(inherited["subject_id"], membership_gid) is False

    backend.invite_membership(
        email=inherited_email,
        first_name="Inherited",
        last_name="Member",
        membership_gid=membership_gid,
        membership_label="Invite Membership",
        invite_url="https://example.test/invite",
    )

    assert backend.has_direct_membership(inherited["subject_id"], membership_gid) is True
    assert inbox_path.exists() is False

    new_email = f"invite-new-{uuid.uuid4().hex}@example.test"
    backend.invite_membership(
        email=new_email,
        first_name="New",
        last_name="Member",
        membership_gid=membership_gid,
        membership_label="Invite Membership",
        invite_url="https://example.test/invite",
    )

    new_candidate = backend.lookup_invite_candidate(new_email, membership_gid)["exact_match"]
    assert new_candidate is not None
    assert backend.has_direct_membership(new_candidate["subject_id"], membership_gid) is True
    assert inbox_path.read_text(encoding="utf-8").count("\n") == 1


def test_resolve_invite_state_blocks_when_candidate_already_exists(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    seeded_rbac: AuthRbac,
) -> None:
    """Invite state should block new invites when an identity for that email already exists."""
    assert migrated_db_per_file is None

    backend = _make_auth_support_backend(db_per_file)
    membership_gid = _create_membership_target(seeded_rbac, db_per_file, "Invite State Membership")
    existing_email = f"invite-existing-{uuid.uuid4().hex}@example.test"
    invited = backend.create_invited_identity(existing_email, "Existing", "Invitee")
    backend.grant_invited_membership(invited["subject_id"], membership_gid)

    values = invite_values({"email": existing_email, "first_name": "", "last_name": ""})
    errors: dict[str, str] = {}
    state = resolve_invite_state(
        auth_support=backend,
        target_gid=membership_gid,
        values=values,
        errors=errors,
    )

    assert state["candidate"] is not None
    assert state["candidate"]["subject_id"] == invited["subject_id"]
    assert state["candidate"]["email"] == existing_email
    assert state["candidate_mode"] == "new"
    assert errors == {
        "email": "Er bestaat inmiddels al een gebruiker of uitnodiging voor dit e-mailadres.",
    }


def test_resolve_invite_step_invite_requires_first_and_last_name(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    seeded_rbac: AuthRbac,
) -> None:
    """Invite step should require both names before allowing invite creation."""
    assert migrated_db_per_file is None

    backend = _make_auth_support_backend(db_per_file)
    membership_gid = _create_membership_target(seeded_rbac, db_per_file, "Invite Name Validation Membership")
    email = f"invite-new-{uuid.uuid4().hex}@example.test"

    missing_values = invite_values({"email": email, "first_name": "", "last_name": ""})
    missing_errors: dict[str, str] = {}
    missing_resolution = resolve_invite_step(
        auth_support=backend,
        step="invite",
        request_data={},
        target_gid=membership_gid,
        values=missing_values,
        errors=missing_errors,
    )

    assert missing_resolution["should_create_invite"] is False
    assert missing_resolution["should_grant_membership"] is False
    assert missing_resolution["state"] == {
        "candidate": None,
        "candidate_mode": "new",
    }
    assert missing_errors == {
        "first_name": "Vul een voornaam in.",
        "last_name": "Vul een achternaam in.",
    }

    valid_values = invite_values({"email": email, "first_name": "New", "last_name": "Invitee"})
    valid_errors: dict[str, str] = {}
    valid_resolution = resolve_invite_step(
        auth_support=backend,
        step="invite",
        request_data={},
        target_gid=membership_gid,
        values=valid_values,
        errors=valid_errors,
    )

    assert valid_resolution["should_create_invite"] is True
    assert valid_resolution["should_grant_membership"] is False
    assert valid_resolution["state"] == {
        "candidate": None,
        "candidate_mode": "new",
    }
    assert valid_errors == {}


def test_resolve_invite_step_grant_rejects_stale_subject(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    seeded_rbac: AuthRbac,
) -> None:
    """Grant step should fail when the submitted subject id no longer matches lookup state."""
    assert migrated_db_per_file is None

    backend = _make_auth_support_backend(db_per_file)
    membership_gid = _create_membership_target(seeded_rbac, db_per_file, "Invite Grant Membership")
    candidate_email = f"invite-grant-{uuid.uuid4().hex}@example.test"
    invited = backend.create_invited_identity(candidate_email, "Grant", "Candidate")

    values = invite_values({"email": candidate_email, "first_name": "", "last_name": ""})
    errors: dict[str, str] = {}
    stale_subject_id = str(uuid.uuid4())
    resolution = resolve_invite_step(
        auth_support=backend,
        step="grant",
        request_data={
            "subject_id": stale_subject_id,
            "match_kind": "exact",
        },
        target_gid=membership_gid,
        values=values,
        errors=errors,
    )

    assert invited["subject_id"] != stale_subject_id
    assert resolution["should_grant_membership"] is False
    assert resolution["should_create_invite"] is False
    assert resolution["state"] == {
        "candidate": None,
        "candidate_mode": "exact",
    }
    assert errors == {
        "email": "De gevonden gebruiker kon niet meer bevestigd worden.",
    }


def test_resolve_lookup_and_grant_state_enforces_candidate_consistency(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    seeded_rbac: AuthRbac,
) -> None:
    """Lookup/grant should keep exact/similar candidates consistent and reject unsafe confirmations."""
    assert migrated_db_per_file is None

    backend = _make_auth_support_backend(db_per_file)
    membership_gid = _create_membership_target(
        seeded_rbac,
        db_per_file,
        "Invite Candidate Consistency Membership",
    )
    suffix = uuid.uuid4().hex

    exact_email = f"invite-exact-{suffix}@example.test"
    exact_candidate = backend.create_invited_identity(exact_email, "Exact", "Candidate")

    similar_email = f"invite.similar.{suffix}@example.test"
    similar_candidate = backend.create_invited_identity(similar_email, "Similar", "Candidate")
    backend.grant_invited_membership(similar_candidate["subject_id"], membership_gid)

    exact_values = invite_values({"email": exact_email, "first_name": "", "last_name": ""})
    exact_lookup_errors: dict[str, str] = {}
    exact_lookup_state = resolve_lookup_state(
        auth_support=backend,
        target_gid=membership_gid,
        values=exact_values,
        errors=exact_lookup_errors,
    )

    assert exact_lookup_state["candidate_mode"] == "exact"
    assert exact_lookup_state["candidate"] is not None
    assert exact_lookup_state["candidate"]["subject_id"] == exact_candidate["subject_id"]
    assert exact_lookup_errors == {}

    similar_values = invite_values({"email": f"invitesimilar{suffix}@example.test", "first_name": "", "last_name": ""})
    similar_lookup_errors: dict[str, str] = {}
    similar_lookup_state = resolve_lookup_state(
        auth_support=backend,
        target_gid=membership_gid,
        values=similar_values,
        errors=similar_lookup_errors,
    )

    assert similar_lookup_state["candidate_mode"] == "similar"
    assert similar_lookup_state["candidate"] is not None
    assert similar_lookup_state["candidate"]["subject_id"] == similar_candidate["subject_id"]
    assert similar_lookup_errors == {
        "email": "Deze gebruiker is al lid van deze organisatie.",
    }

    stale_grant_errors: dict[str, str] = {}
    stale_grant_state = resolve_grant_state(
        auth_support=backend,
        request_data={
            "subject_id": str(uuid.uuid4()),
            "match_kind": "exact",
        },
        target_gid=membership_gid,
        values=exact_values,
        errors=stale_grant_errors,
    )

    assert stale_grant_state == {
        "candidate": None,
        "candidate_mode": "exact",
    }
    assert stale_grant_errors == {
        "email": "De gevonden gebruiker kon niet meer bevestigd worden.",
    }

    invalid_kind_errors: dict[str, str] = {}
    invalid_kind_state = resolve_grant_state(
        auth_support=backend,
        request_data={
            "subject_id": exact_candidate["subject_id"],
            "match_kind": "new",
        },
        target_gid=membership_gid,
        values=exact_values,
        errors=invalid_kind_errors,
    )

    assert invalid_kind_state == {
        "candidate": None,
        "candidate_mode": "",
    }
    assert invalid_kind_errors == {
        "email": "De gevonden gebruiker kon niet meer bevestigd worden.",
    }

    similar_grant_errors: dict[str, str] = {}
    similar_grant_state = resolve_grant_state(
        auth_support=backend,
        request_data={
            "subject_id": similar_candidate["subject_id"],
            "match_kind": "similar",
        },
        target_gid=membership_gid,
        values=similar_values,
        errors=similar_grant_errors,
    )

    assert similar_grant_state["candidate_mode"] == "similar"
    assert similar_grant_state["candidate"] is not None
    assert similar_grant_state["candidate"]["subject_id"] == similar_candidate["subject_id"]
    assert similar_grant_errors == {
        "email": "Deze gebruiker is al lid van deze organisatie.",
    }
