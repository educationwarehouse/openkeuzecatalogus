"""Tests for shared membership query helpers."""

import typing as t
import uuid

from edwh_auth_rbac import AuthRbac
from typedal import TypeDAL

from shared_code.data_model import AuthUser, OrganisationEd, Supplier
from shared_code.data_model.constants import OrganisationType
from shared_code.data_model.constants.organisation import ORG_TYPE_LABELS
from shared_code.modules.auth.user_memberships import (
    build_user_query,
    count_members,
    membership_label,
    user_organisation_memberships,
)


def _insert_organisation(
    name: str,
    organisation_type: OrganisationType,
    *,
    email_domains: list[str] | None = None,
) -> OrganisationEd:
    """Create one effective-dated organisation row for membership tests."""
    row = OrganisationEd.insert(
        name=name,
        organisation_type=organisation_type.value,
        email_domains=email_domains or [],
    )
    assert row is not None
    return row


def test_count_members_and_build_user_query_filter_direct_memberships(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    auth_user_factory: t.Callable[..., AuthUser],
    seeded_rbac: AuthRbac,
) -> None:
    """Direct membership helpers should count and filter users by one membership."""
    assert migrated_db_per_file is None

    supplier = supplier_factory(name="Query Supplier", email_domains=["query-members.example.test"])
    member_one = auth_user_factory(prefix="member-one")
    member_two = auth_user_factory(prefix="member-two")
    outsider = auth_user_factory(prefix="outsider")

    seeded_rbac.add_membership(str(member_one.gid), str(supplier.gid))
    seeded_rbac.add_membership(str(member_two.gid), str(supplier.gid))
    db_per_file.commit()

    assert count_members(str(supplier.gid)) == 2

    rows = AuthUser.where(build_user_query(membership_gid=str(supplier.gid))).select(AuthUser.gid).collect()
    row_gids = {str(row.gid) for row in rows}

    assert row_gids == {str(member_one.gid), str(member_two.gid)}
    assert str(outsider.gid) not in row_gids


def test_build_user_query_returns_empty_query_for_unknown_membership(
    migrated_db_per_file: None,
) -> None:
    """Unknown membership filters should return no users."""
    assert migrated_db_per_file is None

    rows = list(AuthUser.where(build_user_query(membership_gid="00000000-0000-0000-0000-000000000000")).select())
    assert rows == []


def test_user_organisation_memberships_lists_organisation_and_supplier_memberships(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    auth_user_factory: t.Callable[..., AuthUser],
    seeded_rbac: AuthRbac,
) -> None:
    """Membership details should include both organisation and supplier groups."""
    assert migrated_db_per_file is None

    board = _insert_organisation(
        "Membership Board",
        OrganisationType.BOARD,
        email_domains=["membership-board.example.test"],
    )
    supplier = supplier_factory(name="Membership Supplier", email_domains=["membership-supplier.example.test"])
    user = auth_user_factory(prefix="membership-user")
    db_per_file.commit()

    seeded_rbac.add_membership(str(user.gid), str(board.gid))
    seeded_rbac.add_membership(str(user.gid), str(supplier.gid))
    db_per_file.commit()

    memberships = user_organisation_memberships(str(user.gid))
    memberships_by_gid = {item["gid"]: item for item in memberships}

    assert memberships_by_gid[str(board.gid)] == {
        "gid": str(board.gid),
        "name": "Membership Board",
        "membership_type": OrganisationType.BOARD.value,
        "type_label": ORG_TYPE_LABELS[OrganisationType.BOARD.value],
    }
    assert memberships_by_gid[str(supplier.gid)] == {
        "gid": str(supplier.gid),
        "name": "Membership Supplier",
        "membership_type": "supplier",
        "type_label": ORG_TYPE_LABELS["supplier"],
    }


def test_membership_label_prefers_known_supplier_or_organisation_name(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
) -> None:
    """Membership labels should resolve known entity names and fall back to the gid."""
    assert migrated_db_per_file is None

    school = _insert_organisation(
        "Membership School",
        OrganisationType.SCHOOL,
        email_domains=["membership-school.example.test"],
    )
    supplier = supplier_factory(name="Label Supplier", email_domains=["label-supplier.example.test"])
    db_per_file.commit()

    assert membership_label(school.gid) == "Membership School"
    assert membership_label(supplier.gid) == "Label Supplier"

    missing_gid = uuid.uuid4()
    assert membership_label(missing_gid) == str(missing_gid)
    assert membership_label(None) is None
