"""Reusable state handling for membership invitation interfaces."""

import typing as t

from shared_code.data_model import AnyDict

from .module import AuthSupportBackend, InviteCandidate


class InviteValues(t.TypedDict):
    """Normalized values supplied by a membership invitation form."""

    email: str
    first_name: str
    last_name: str


InviteCandidateMode = t.Literal["", "exact", "similar", "new"]
InviteStep = t.Literal["lookup", "grant", "invite"]

# Blocks on `direct_member`, not `already_member`: a subject that only inherits access through a
# nested group is absent from this organisation's member list, so granting them a direct
# membership is a real action rather than a duplicate. See `InviteCandidate` for both flags.
ALREADY_MEMBER_ERROR = "Deze gebruiker is al lid van deze organisatie."


class InviteStepState(t.TypedDict):
    """Resolved invite candidate state for one UI step."""

    candidate: InviteCandidate | None
    candidate_mode: InviteCandidateMode


class InviteStepResolution(t.TypedDict):
    """Full step resolution including follow-up action flags."""

    state: InviteStepState
    should_grant_membership: bool
    should_create_invite: bool


def invite_values(request_data: AnyDict) -> InviteValues:
    """Normalize invite form values from merged request data."""
    return InviteValues(
        email=str(request_data.get("email") or "").strip().lower(),
        first_name=str(request_data.get("first_name") or "").strip(),
        last_name=str(request_data.get("last_name") or "").strip(),
    )


def normalize_invite_email(auth_support: AuthSupportBackend, values: InviteValues, errors: dict[str, str]) -> None:
    """Normalize and validate invite email in-place."""
    if errors:
        return

    normalized_email, email_error = auth_support.normalize_invite_email(values["email"])
    if email_error:
        errors["email"] = email_error
        return

    values["email"] = str(normalized_email)


def resolve_lookup_state(
    auth_support: AuthSupportBackend,
    target_gid: str,
    values: InviteValues,
    errors: dict[str, str],
) -> InviteStepState:
    """Resolve candidate preview for the lookup step."""
    if errors:
        return InviteStepState(candidate=None, candidate_mode="")

    lookup = auth_support.lookup_invite_candidate(values["email"], target_gid)
    if lookup["exact_match"]:
        candidate = lookup["exact_match"]
        if candidate["direct_member"]:
            errors["email"] = ALREADY_MEMBER_ERROR
        return InviteStepState(candidate=candidate, candidate_mode="exact")

    elif lookup["similar_match"]:
        candidate = lookup["similar_match"]
        if candidate["direct_member"]:
            errors["email"] = ALREADY_MEMBER_ERROR
        return InviteStepState(candidate=candidate, candidate_mode="similar")
    else:
        return InviteStepState(candidate=None, candidate_mode="new")


# todo: turn into domain/service/mixin of AuthSupportBackend ?


def resolve_grant_state(
    auth_support: AuthSupportBackend,
    request_data: AnyDict,
    target_gid: str,
    values: InviteValues,
    errors: dict[str, str],
) -> InviteStepState:
    """Resolve and validate grant-confirmation payload for one invite candidate."""
    if errors:
        return InviteStepState(candidate=None, candidate_mode="")

    requested_subject_id = str(request_data.get("subject_id") or "")
    requested_match_kind = str(request_data.get("match_kind") or "")
    candidate_mode = t.cast(
        InviteCandidateMode, requested_match_kind if requested_match_kind in ("exact", "similar") else ""
    )

    lookup = auth_support.lookup_invite_candidate(values["email"], target_gid)
    if candidate_mode == "exact":
        candidate = lookup["exact_match"]
    elif candidate_mode == "similar":
        candidate = lookup["similar_match"]
    else:
        candidate = None

    if not candidate or candidate["subject_id"] != requested_subject_id:
        errors["email"] = "De gevonden gebruiker kon niet meer bevestigd worden."
        return InviteStepState(candidate=None, candidate_mode=candidate_mode)

    if candidate["direct_member"]:
        errors["email"] = ALREADY_MEMBER_ERROR

    return InviteStepState(candidate=candidate, candidate_mode=candidate_mode)


def resolve_invite_state(
    auth_support: AuthSupportBackend,
    target_gid: str,
    values: InviteValues,
    errors: dict[str, str],
) -> InviteStepState:
    """Resolve create-invite preconditions, including duplicate protection."""
    if errors:
        return InviteStepState(candidate=None, candidate_mode="new")

    lookup = auth_support.lookup_invite_candidate(values["email"], target_gid)
    candidate = lookup["exact_match"] or lookup["similar_match"]
    if candidate:
        errors["email"] = "Er bestaat inmiddels al een gebruiker of uitnodiging voor dit e-mailadres."

    return InviteStepState(candidate=candidate, candidate_mode="new")


def validate_invite_name_fields(values: InviteValues, errors: dict[str, str]) -> None:
    """Validate required name fields for creating a new invited identity."""
    if not values["first_name"]:
        errors["first_name"] = "Vul een voornaam in."
    if not values["last_name"]:
        errors["last_name"] = "Vul een achternaam in."


def resolve_invite_step(
    auth_support: AuthSupportBackend,
    step: InviteStep,
    request_data: AnyDict,
    target_gid: str,
    values: InviteValues,
    errors: dict[str, str],
) -> InviteStepResolution:
    """Resolve one invite flow step and report which follow-up action is allowed."""
    normalize_invite_email(auth_support, values, errors)

    if step == "lookup":
        state = resolve_lookup_state(auth_support, target_gid, values, errors)
        return InviteStepResolution(state=state, should_grant_membership=False, should_create_invite=False)
    elif step == "grant":
        state = resolve_grant_state(auth_support, request_data, target_gid, values, errors)
        return InviteStepResolution(
            state=state,
            should_grant_membership=bool(state["candidate"] and not errors),
            should_create_invite=False,
        )
    elif step == "invite":
        validate_invite_name_fields(values, errors)
        state = resolve_invite_state(auth_support, target_gid, values, errors)
        return InviteStepResolution(
            state=state,
            should_grant_membership=False,
            should_create_invite=bool(not state["candidate"] and not errors),
        )
    else:
        raise NotImplementedError(f"Invalid {step = }")


def create_and_send_membership_invite(
    auth_support: AuthSupportBackend,
    target_gid: str,
    membership_label: str,
    login_url: str,
    values: InviteValues,
) -> None:
    """Create invited identity, grant membership and send invite mail."""
    invited = auth_support.create_invited_identity(values["email"], values["first_name"], values["last_name"])
    auth_support.grant_invited_membership(invited["subject_id"], target_gid)
    auth_support.send_membership_invite_email(
        email=values["email"],
        membership_label=membership_label,
        invite_url=login_url,
        first_name=values["first_name"],
    )


__all__ = [
    "ALREADY_MEMBER_ERROR",
    "InviteCandidateMode",
    "InviteStep",
    "InviteStepResolution",
    "InviteStepState",
    "InviteValues",
    "create_and_send_membership_invite",
    "invite_values",
    "normalize_invite_email",
    "resolve_grant_state",
    "resolve_invite_state",
    "resolve_invite_step",
    "resolve_lookup_state",
    "validate_invite_name_fields",
]
