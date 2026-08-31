"""Tests for admin invite-flow helpers using real backend flows."""

import uuid

from apps.admin.models.user_invite import (
    invite_values,
    resolve_grant_state,
    resolve_invite_state,
    resolve_invite_step,
    resolve_lookup_state,
)
from common.models import backend, db

from shared_code.data_model import SupplierEd
from shared_code.util.olid import generate_supplier_olid


def _create_supplier_membership(name: str) -> str:
    """Create one supplier membership target and return its gid."""
    supplier_gid = str(uuid.uuid4())
    SupplierEd.insert(
        gid=supplier_gid,
        name=name,
        olid=generate_supplier_olid(supplier_gid),
        email_domains=[f"{uuid.uuid4().hex}.example.test"],
        endpoint_type="none",
        status_visions="compleet",
    )
    db.commit()
    return supplier_gid


def test_resolve_invite_state_blocks_when_candidate_already_exists() -> None:
    """Invite state should block new invites when an identity for that email already exists."""
    membership_gid = _create_supplier_membership("Invite State Membership")
    existing_email = f"invite-existing-{uuid.uuid4().hex}@example.test"
    invited = backend.auth_support.create_invited_identity(existing_email, "Existing", "Invitee")
    backend.auth_support.grant_invited_membership(invited["subject_id"], membership_gid)

    values = invite_values({"email": existing_email, "first_name": "", "last_name": ""})
    errors: dict[str, str] = {}
    state = resolve_invite_state(membership_gid, values, errors)

    assert state["candidate"] is not None
    assert state["candidate"]["subject_id"] == invited["subject_id"]
    assert state["candidate"]["email"] == existing_email
    assert state["candidate_mode"] == "new"
    assert errors == {
        "email": "Er bestaat inmiddels al een gebruiker of uitnodiging voor dit e-mailadres.",
    }


def test_resolve_invite_step_invite_requires_first_and_last_name() -> None:
    """Invite step should require both names before allowing invite creation."""
    membership_gid = _create_supplier_membership("Invite Name Validation Membership")
    email = f"invite-new-{uuid.uuid4().hex}@example.test"

    missing_values = invite_values({"email": email, "first_name": "", "last_name": ""})
    missing_errors: dict[str, str] = {}
    missing_resolution = resolve_invite_step("invite", {}, membership_gid, missing_values, missing_errors)

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
    valid_resolution = resolve_invite_step("invite", {}, membership_gid, valid_values, valid_errors)

    assert valid_resolution["should_create_invite"] is True
    assert valid_resolution["should_grant_membership"] is False
    assert valid_resolution["state"] == {
        "candidate": None,
        "candidate_mode": "new",
    }
    assert valid_errors == {}


def test_resolve_invite_step_grant_rejects_stale_subject() -> None:
    """Grant step should fail when the submitted subject id no longer matches lookup state."""
    membership_gid = _create_supplier_membership("Invite Grant Membership")
    candidate_email = f"invite-grant-{uuid.uuid4().hex}@example.test"
    invited = backend.auth_support.create_invited_identity(candidate_email, "Grant", "Candidate")

    values = invite_values({"email": candidate_email, "first_name": "", "last_name": ""})
    errors: dict[str, str] = {}
    stale_subject_id = str(uuid.uuid4())
    resolution = resolve_invite_step(
        "grant",
        {
            "subject_id": stale_subject_id,
            "match_kind": "exact",
        },
        membership_gid,
        values,
        errors,
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


def test_resolve_lookup_and_grant_state_enforces_candidate_consistency() -> None:
    """Lookup/grant should keep exact/similar candidates consistent and reject unsafe confirmations."""
    membership_gid = _create_supplier_membership("Invite Candidate Consistency Membership")
    suffix = uuid.uuid4().hex

    exact_email = f"invite-exact-{suffix}@example.test"
    exact_candidate = backend.auth_support.create_invited_identity(exact_email, "Exact", "Candidate")

    similar_email = f"invite.similar.{suffix}@example.test"
    similar_candidate = backend.auth_support.create_invited_identity(similar_email, "Similar", "Candidate")
    backend.auth_support.grant_invited_membership(similar_candidate["subject_id"], membership_gid)

    exact_values = invite_values({"email": exact_email, "first_name": "", "last_name": ""})
    exact_lookup_errors: dict[str, str] = {}
    exact_lookup_state = resolve_lookup_state(membership_gid, exact_values, exact_lookup_errors)

    assert exact_lookup_state["candidate_mode"] == "exact"
    assert exact_lookup_state["candidate"] is not None
    assert exact_lookup_state["candidate"]["subject_id"] == exact_candidate["subject_id"]
    assert exact_lookup_errors == {}

    similar_values = invite_values({"email": f"invitesimilar{suffix}@example.test", "first_name": "", "last_name": ""})
    similar_lookup_errors: dict[str, str] = {}
    similar_lookup_state = resolve_lookup_state(membership_gid, similar_values, similar_lookup_errors)

    assert similar_lookup_state["candidate_mode"] == "similar"
    assert similar_lookup_state["candidate"] is not None
    assert similar_lookup_state["candidate"]["subject_id"] == similar_candidate["subject_id"]
    assert similar_lookup_errors == {
        "email": "Deze gebruiker heeft al toegang tot deze organisatie.",
    }

    stale_grant_errors: dict[str, str] = {}
    stale_grant_state = resolve_grant_state(
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
        "email": "Deze gebruiker heeft al toegang tot deze organisatie.",
    }
