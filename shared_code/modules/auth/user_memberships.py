"""Shared membership query helpers for auth/admin flows."""

import typing as t
import uuid

from typedal.types import Query, Rows

from shared_code.data_model import AuthUser, Organisation, Supplier
from shared_code.data_model.constants.organisation import ORG_TYPE_LABELS
from shared_code.modules.auth.module import InviteCandidate


class UserOrganisationMembership(t.TypedDict):
    """Direct organisation-like membership metadata for one user."""

    gid: str
    name: str
    membership_type: str
    type_label: str


def count_members(member_of_gid: str) -> int:
    """Return the number of distinct users directly linked to one membership."""
    db = AuthUser._db
    assert db

    return db(db.membership.member_of == member_of_gid).count(distinct=db.membership.subject)


def build_user_query(membership_gid: str | None = None) -> Query:
    """Build the base user query, optionally limited to one direct membership."""
    db = AuthUser._db
    assert db, "can't continue without db"

    query: Query = AuthUser.id > 0

    if not membership_gid:
        return query

    member_subject_rows: Rows = db(db.membership.member_of == membership_gid).select(
        db.membership.subject,
        groupby=db.membership.subject,
    )
    member_subjects = [str(row.subject) for row in member_subject_rows if row.subject]
    if not member_subjects:
        return AuthUser.id == 0
    query &= AuthUser.gid.belongs(member_subjects)

    return query


def user_organisation_memberships(user_gid: str) -> list[UserOrganisationMembership]:
    """Return the direct board/school/location/supplier memberships for one user."""
    db = AuthUser._db
    assert db, "can't continue without db"

    membership_rows: Rows = db(db.membership.subject == user_gid).select(
        db.membership.member_of,
        groupby=db.membership.member_of,
    )
    member_of_gids = [row.member_of for row in membership_rows if row.member_of]
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

    return str(member_of_gid)


def pending_membership_invites(member_of_gid: str) -> list[InviteCandidate]:
    """Return direct membership invites not yet linked to an `AuthUser` row."""
    db = AuthUser._db
    assert db, "can't continue without db"

    membership_rows: Rows = db(db.membership.member_of == member_of_gid).select(
        db.membership.subject,
        groupby=db.membership.subject,
    )
    subject_ids = [str(row.subject) for row in membership_rows if row.subject]
    if not subject_ids:
        return []

    existing_user_rows = AuthUser.where(AuthUser.gid.belongs(subject_ids)).select(AuthUser.gid)
    existing_user_gids = {str(row.gid) for row in existing_user_rows}
    pending_subject_ids = [subject_id for subject_id in subject_ids if subject_id not in existing_user_gids]
    if not pending_subject_ids:
        return []

    identity_rows = db(
        (db.identity.object_type == "user") & (db.identity.object_id.belongs(pending_subject_ids)),
    ).select(
        db.identity.object_id,
        db.identity.email,
        db.identity.fullname,
        db.identity.firstname,
        orderby=db.identity.email,
    )

    return [
        InviteCandidate(
            subject_id=identity.object_id,
            email=identity.email or "",
            full_name=identity.fullname or identity.firstname or identity.email or "",
            source="identity",
            already_member=True,
        )
        for identity in identity_rows
    ]
