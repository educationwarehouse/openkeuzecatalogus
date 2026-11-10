"""Organisation RBAC permission regression checks."""

import typing as t

import pytest
from edwh_auth_rbac import AuthRbac

from shared_code.data_model import AuthUser, OrganisationEd
from shared_code.data_model.constants import OrganisationType
from shared_code.infra.database import DatabaseContext
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.organisations import OrganisationBackend

BOARD_GID = "dc0874bb-0901-406b-8567-c646e61eeb3b"
SCHOOL_NOORD_GID = "9f5788bd-d8c5-428c-b61e-0b980733275b"
SCHOOL_ZUID_GID = "339d3e16-2939-4782-bf64-130079629fda"
VESTIGING_CENTRUM_GID = "db1e5f11-b1d0-4ca2-b350-57e089fe159d"
VESTIGING_RIJN_GID = "00def74c-7ca1-4f02-9012-465dad97706e"


def _make_backend(auth_adapter: AuthAdapter, db: DatabaseContext) -> OrganisationBackend:
    """Construct an organisation backend with endow injection."""
    return OrganisationBackend.with_injected(
        db=db,
        auth_adapter=auth_adapter,
    )


def _insert_organisation(
    name: str,
    organisation_type: OrganisationType,
    email_domains: list[str] | None = None,
) -> OrganisationEd:
    """Create one effective-dated organisation row for RBAC tests."""
    row = OrganisationEd.insert(
        name=name,
        organisation_type=organisation_type.value,
        email_domains=email_domains or [],
    )
    assert row is not None
    return row


def _assert_permission_shape(
    rbac: AuthRbac,
    board_member: AuthUser,
    school_zuid_member: AuthUser,
    vestiging_centrum_member: AuthUser,
    *,
    board_gid: str,
    school_noord_gid: str,
    school_zuid_gid: str,
    vestiging_centrum_gid: str,
    vestiging_rijn_gid: str,
) -> None:
    """Assert the expected organisation permission contract for one hierarchy."""
    assert rbac.has_permission(board_member.gid, board_gid, "read")
    assert rbac.has_permission(board_member.gid, board_gid, "write")
    assert rbac.has_permission(board_member.gid, school_noord_gid, "read")
    assert not rbac.has_permission(board_member.gid, school_noord_gid, "write")
    assert rbac.has_permission(board_member.gid, school_zuid_gid, "read")
    assert not rbac.has_permission(board_member.gid, school_zuid_gid, "write")
    assert rbac.has_permission(board_member.gid, vestiging_centrum_gid, "read")
    assert not rbac.has_permission(board_member.gid, vestiging_centrum_gid, "write")

    assert rbac.has_permission(school_zuid_member.gid, school_zuid_gid, "read")
    assert rbac.has_permission(school_zuid_member.gid, school_zuid_gid, "write")
    assert rbac.has_permission(school_zuid_member.gid, vestiging_rijn_gid, "read")
    assert rbac.has_permission(school_zuid_member.gid, vestiging_rijn_gid, "write")
    assert not rbac.has_permission(school_zuid_member.gid, vestiging_centrum_gid, "read")
    assert not rbac.has_permission(school_zuid_member.gid, vestiging_centrum_gid, "write")
    assert rbac.has_permission(school_zuid_member.gid, board_gid, "read")
    assert not rbac.has_permission(school_zuid_member.gid, board_gid, "write")

    assert rbac.has_permission(vestiging_centrum_member.gid, vestiging_centrum_gid, "read")
    assert rbac.has_permission(vestiging_centrum_member.gid, vestiging_centrum_gid, "write")
    assert rbac.has_permission(vestiging_centrum_member.gid, board_gid, "read")
    assert not rbac.has_permission(vestiging_centrum_member.gid, board_gid, "write")


def test_seeded_organisation_permissions(
    seeded_rbac: AuthRbac,
    auth_user_factory,
) -> None:
    """Verify seeded organisation permissions on the example hierarchy."""

    # based on organisation_relations.json, check that
    # - a member of Voorbeeldbestuur may read but not write School Noord, School Zuid, and Vestiging Centrum
    # - a member of School Zuid has no access to Vestiging Centrum
    # - a member of vestiging Centrum only has read-access to Voorbeeldbestuur

    board_member = auth_user_factory(prefix="board-member", roles=[BOARD_GID])
    school_zuid_member = auth_user_factory(prefix="school-zuid-member", roles=[SCHOOL_ZUID_GID])
    vestiging_centrum_member = auth_user_factory(prefix="vestiging-centrum-member", roles=[VESTIGING_CENTRUM_GID])

    _assert_permission_shape(
        seeded_rbac,
        board_member,
        school_zuid_member,
        vestiging_centrum_member,
        board_gid=BOARD_GID,
        school_noord_gid=SCHOOL_NOORD_GID,
        school_zuid_gid=SCHOOL_ZUID_GID,
        vestiging_centrum_gid=VESTIGING_CENTRUM_GID,
        vestiging_rijn_gid=VESTIGING_RIJN_GID,
    )


@pytest.mark.parametrize("actor_kind", ["admin", "service"])
def test_new_organisation_permissions_for_privileged_actor(
    actor_kind: str,
    db_per_file: DatabaseContext,
    seeded_rbac: AuthRbac,
    auth_user_factory: t.Callable[..., AuthUser],
    auth_adapter_factory: t.Callable[..., AuthAdapter],
    admin_user: AuthUser,
) -> None:
    """New organisation relations should work for admin and service callers."""
    board = _insert_organisation(
        "Fresh Board",
        OrganisationType.BOARD,
        email_domains=[f"fresh-board-{actor_kind}.example.test"],
    )
    school_noord = _insert_organisation(
        "Fresh School Noord",
        OrganisationType.SCHOOL,
        email_domains=[f"fresh-school-noord-{actor_kind}.example.test"],
    )
    school_zuid = _insert_organisation(
        "Fresh School Zuid",
        OrganisationType.SCHOOL,
        email_domains=[f"fresh-school-zuid-{actor_kind}.example.test"],
    )
    vestiging_centrum = _insert_organisation(
        "Fresh Vestiging Centrum",
        OrganisationType.LOCATION,
        email_domains=[f"fresh-vestiging-centrum-{actor_kind}.example.test"],
    )
    vestiging_rijn = _insert_organisation(
        "Fresh Vestiging Rijn",
        OrganisationType.LOCATION,
        email_domains=[f"fresh-vestiging-rijn-{actor_kind}.example.test"],
    )
    db_per_file.commit()

    privileged_auth = (
        auth_adapter_factory(admin_user) if actor_kind == "admin" else AuthAdapter.for_service("pytest.organisations")
    )
    backend = _make_backend(privileged_auth, db_per_file)
    rbac = backend.auth.raw_rbac

    backend.connect_board_to_school(board.gid, school_noord.gid)
    backend.connect_board_to_school(board.gid, school_zuid.gid)
    backend.connect_school_to_location(school_noord.gid, vestiging_centrum.gid)
    backend.connect_school_to_location(school_zuid.gid, vestiging_rijn.gid)

    board_member = auth_user_factory(prefix="board-member", domain=f"fresh-board-{actor_kind}.example.test")
    school_zuid_member = auth_user_factory(
        prefix="school-zuid-member",
        domain=f"fresh-school-zuid-{actor_kind}.example.test",
    )
    vestiging_centrum_member = auth_user_factory(
        prefix="vestiging-centrum-member",
        domain=f"fresh-vestiging-centrum-{actor_kind}.example.test",
    )

    backend.grant_memberships(board_member)
    backend.grant_memberships(school_zuid_member)
    backend.grant_memberships(vestiging_centrum_member)

    backend.db.commit()

    assert rbac.has_membership(board_member.gid, board.gid)
    assert rbac.has_membership(school_zuid_member.gid, school_zuid.gid)
    assert rbac.has_membership(vestiging_centrum_member.gid, vestiging_centrum.gid)

    _assert_permission_shape(
        backend.auth.raw_rbac,
        board_member,
        school_zuid_member,
        vestiging_centrum_member,
        board_gid=board.gid,
        school_noord_gid=school_noord.gid,
        school_zuid_gid=school_zuid.gid,
        vestiging_centrum_gid=vestiging_centrum.gid,
        vestiging_rijn_gid=vestiging_rijn.gid,
    )


def test_new_organisation_permissions_for_regular_user_fails(
    db_per_file: DatabaseContext,
    auth_user_factory: t.Callable[..., AuthUser],
    auth_adapter_factory: t.Callable[..., AuthAdapter],
) -> None:
    """Regular users may not mutate organisation relations through the backend."""
    board = _insert_organisation("Denied Board", OrganisationType.BOARD)
    school = _insert_organisation("Denied School", OrganisationType.SCHOOL)
    location = _insert_organisation("Denied Location", OrganisationType.LOCATION)
    db_per_file.commit()

    user = auth_user_factory(prefix="org-regular-user")
    user_backend = _make_backend(auth_adapter_factory(user), db_per_file)
    service_backend = _make_backend(AuthAdapter.for_service("pytest.organisations.setup"), db_per_file)

    with pytest.raises(PermissionError):
        user_backend.connect_board_to_school(board.gid, school.gid)

    service_backend.connect_board_to_school(board.gid, school.gid)

    with pytest.raises(PermissionError):
        user_backend.connect_school_to_location(school.gid, location.gid)
