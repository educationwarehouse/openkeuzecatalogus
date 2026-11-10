"""Shared membership query helpers for auth/admin flows."""

import typing as t
import uuid

from typedal.types import Query

from shared_code.data_model import (
    AuthUser,
    DecisionTeam,
    Identity,
    Membership,
    Organisation,
    RecursiveMembers,
    Supplier,
)
from shared_code.data_model.constants.organisation import ORG_TYPE_LABELS
from shared_code.modules.auth.module import InviteCandidate


class UserOrganisationMembership(t.TypedDict):
    """Direct organisation-like membership metadata for one user."""

    gid: str
    name: str
    membership_type: str
    type_label: str


DEFAULT_MEMBER_LEVELS = 1


def _member_query(group_gid: str, max_level: int) -> Query:
    """Build the `recursive_members` query for the user members of one group.

    `level` counts hops from the root: 0 is the group itself, 1 its direct members, 2 the
    members of a group nested one deep. `max_level` of 0 means unlimited.

    todo: `max_level` cannot distinguish nesting that models a *role* (a school's '@directie'
     group, whose members are school staff) from nesting that models *sub-organisations* (the
     schools under a board, whose members are not board staff). Callers therefore pick a depth
     per grid, and two grids over the same entity have historically picked differently. Fixing
     that needs the predicate, not the depth.
    """
    query: Query = (RecursiveMembers.root == group_gid) & (RecursiveMembers.object_type == "user")
    if max_level:
        query &= RecursiveMembers.level <= max_level
    return query


def count_members(member_of_gid: str, max_level: int = DEFAULT_MEMBER_LEVELS) -> int:
    """Return the number of distinct users reachable as members of one group."""
    return RecursiveMembers.where(_member_query(member_of_gid, max_level)).count(distinct=RecursiveMembers.object_id)


def direct_member_gids(member_of_gid: str) -> set[str]:
    """Return the user gids linked to one membership by a *direct* `membership` row.

    Only these can be revoked by `revoke_invited_membership`: an inherited member has no row
    to delete, so an unlink would silently do nothing.
    """
    return set(Membership.where(Membership.member_of == member_of_gid).column(Membership.subject, distinct=True))


def build_user_query(membership_gid: str | None = None, max_level: int = DEFAULT_MEMBER_LEVELS) -> Query:
    """Build the base user query, optionally limited to the members of one group.

    Uses the same depth-bounded definition as `count_members`, so a grid and the badge that
    links to it cannot disagree about who counts as a member.
    """
    query: Query = AuthUser.id > 0

    if not membership_gid:
        return query

    member_subjects = recursive_member_gids(membership_gid, max_level=max_level)
    if not member_subjects:
        return AuthUser.id == 0

    return query & AuthUser.gid.belongs(member_subjects)


def user_organisation_memberships(user_gid: str) -> list[UserOrganisationMembership]:
    """Return the direct board/school/location/supplier memberships for one user."""
    member_of_gids = Membership.where(Membership.subject == user_gid).column(Membership.member_of, distinct=True)
    if not member_of_gids:
        return []

    organisation_rows = Organisation.where(Organisation.gid.belongs(member_of_gids)).select(
        Organisation.gid,
        Organisation.name,
        Organisation.organisation_type,
    )

    items = [
        UserOrganisationMembership(
            gid=row.gid,
            name=row.name,
            membership_type=row.organisation_type,
            type_label=ORG_TYPE_LABELS.get(row.organisation_type, row.organisation_type),
        )
        for row in organisation_rows
    ]

    supplier_rows = Supplier.where(Supplier.gid.belongs(member_of_gids)).select(Supplier.gid, Supplier.name)
    items.extend(
        UserOrganisationMembership(
            gid=row.gid,
            name=row.name,
            membership_type="supplier",
            type_label=ORG_TYPE_LABELS["supplier"],
        )
        for row in supplier_rows
    )
    return items


def membership_label(member_of_gid: str | uuid.UUID | None) -> str | None:
    """Resolve a human-readable label for a membership filter."""
    if not member_of_gid:
        return None

    if organisation := Organisation.where(gid=member_of_gid).select(Organisation.name).first():
        return str(organisation.name or member_of_gid)

    if supplier := Supplier.where(gid=member_of_gid).select(Supplier.name).first():
        return str(supplier.name or member_of_gid)

    if team := DecisionTeam.where(gid=member_of_gid).select(DecisionTeam.name).first():
        return str(team.name or member_of_gid)

    return str(member_of_gid)


def recursive_member_gids(group_gid: str, max_level: int = 0) -> list[str]:
    """Return user members of a group, following nested groups.

    Unlike `pending_membership_invites`, which looks at direct `membership` rows only, this
    reads the recursive view. `max_level` caps the nesting depth; 0 means unlimited.
    """
    return RecursiveMembers.where(_member_query(group_gid, max_level)).column(RecursiveMembers.object_id)


def members_and_pending(gid: str, max_level: int = 1) -> tuple[list[AuthUser], list[InviteCandidate]]:
    """Return registered users of a group plus its outstanding identity invitations."""
    member_gids = recursive_member_gids(gid, max_level=max_level)
    members = AuthUser.where(AuthUser.gid.belongs(member_gids)).collect()
    member_ids = {member.gid for member in members}
    pending = [invite for invite in pending_membership_invites(gid) if invite["subject_id"] not in member_ids]
    return list(members), pending


def pending_membership_invites(member_of_gid: str) -> list[InviteCandidate]:
    """Return direct membership invites not yet linked to an `AuthUser` row."""
    subject_ids = Membership.where(Membership.member_of == member_of_gid).column(Membership.subject, distinct=True)
    if not subject_ids:
        return []

    existing_user_rows = AuthUser.where(AuthUser.gid.belongs(subject_ids)).select(AuthUser.gid)
    existing_user_gids = {row.gid for row in existing_user_rows}
    pending_subject_ids = [subject_id for subject_id in subject_ids if subject_id not in existing_user_gids]
    if not pending_subject_ids:
        return []

    identity_rows = (
        Identity.where((Identity.object_type == "user") & (Identity.object_id.belongs(pending_subject_ids)))
        .select(
            Identity.object_id,
            Identity.email,
            Identity.fullname,
            Identity.firstname,
            orderby=Identity.email,
        )
        .collect()
    )

    return [
        InviteCandidate(
            subject_id=identity.object_id,
            email=identity.email or "",
            full_name=identity.fullname or identity.firstname or identity.email or "",
            source="identity",
            already_member=True,
            # these are read from `membership` rows, so they are direct by construction
            direct_member=True,
        )
        for identity in identity_rows
    ]
