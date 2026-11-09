"""Per-process RBAC regression checks for the guided decision process.

Every wizard route guards on `auth.requires_permission(...)` against the *process* gid, and
`edwh_auth_rbac.has_permission` resolves the target through `recursive_memberships`, so a
gid that is not a registered identity can never carry a permission. These tests pin down that
`create_process` registers the process below its team, and that the existing
board → school → vestiging → vakgroep grants therefore reach it unchanged.

Asserted against `rbac.has_permission` directly rather than through `AuthContext`, because
the shared test adapter does not wire RBAC into `check_permission` (see `conftest`'s
`_build_auth_adapter`) - the same reason `test_organisation_rbac` does it that way.
"""

import typing as t

import pytest
from edwh_auth_rbac import AuthRbac

from shared_code.data_model import AuthUser
from shared_code.infra.database import DatabaseContext
from shared_code.migrations.migration_support.organisation import backfill_organisation_rbac_permissions_v2
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.decision_processes import DecisionProcessBackend

# from organisation_relations.json, same hierarchy as test_organisation_rbac
BOARD_GID = "dc0874bb-0901-406b-8567-c646e61eeb3b"
SCHOOL_NOORD_GID = "9f5788bd-d8c5-428c-b61e-0b980733275b"
SCHOOL_ZUID_GID = "339d3e16-2939-4782-bf64-130079629fda"
VESTIGING_CENTRUM_GID = "db1e5f11-b1d0-4ca2-b350-57e089fe159d"


@pytest.fixture()
def admin_backend(
    db_per_file: DatabaseContext,
    admin_user: AuthUser,
    auth_adapter_factory: t.Callable[..., AuthAdapter],
) -> DecisionProcessBackend:
    """Return a decision-process backend acting as an admin."""
    return DecisionProcessBackend.with_injected(
        db=db_per_file,
        auth_adapter=auth_adapter_factory(admin_user),
    )


def test_created_process_inherits_team_permissions(
    admin_backend: DecisionProcessBackend,
    seeded_rbac: AuthRbac,
    auth_user_factory: t.Callable[..., AuthUser],
) -> None:
    """A vakgroep member may write the processes of that vakgroep."""
    team = admin_backend.create_team(location_gid=VESTIGING_CENTRUM_GID, name="Vakgroep Rekenen")
    process = admin_backend.create_process(team.gid, "2026-2027")

    team_member = auth_user_factory(prefix="team-member", roles=[team.gid])
    outsider = auth_user_factory(prefix="outsider")

    assert seeded_rbac.has_permission(team_member.gid, process.gid, "read")
    assert seeded_rbac.has_permission(team_member.gid, process.gid, "write")

    assert not seeded_rbac.has_permission(outsider.gid, process.gid, "read")
    assert not seeded_rbac.has_permission(outsider.gid, process.gid, "write")


def test_process_permissions_follow_the_organisation_hierarchy(
    admin_backend: DecisionProcessBackend,
    seeded_rbac: AuthRbac,
    auth_user_factory: t.Callable[..., AuthUser],
) -> None:
    """Organisation members may only write decision processes in their own scope.

    Vestiging Centrum hangs below School Noord. Board members and the owning school can inspect
    its process, while other schools cannot access it and only the owning team may edit its
    workflow.
    """
    team = admin_backend.create_team(location_gid=VESTIGING_CENTRUM_GID, name="Vakgroep Nederlands")
    process = admin_backend.create_process(team.gid, "2026-2027")

    board_member = auth_user_factory(prefix="board-member", roles=[BOARD_GID])
    school_noord_member = auth_user_factory(prefix="school-noord-member", roles=[SCHOOL_NOORD_GID])
    school_zuid_member = auth_user_factory(prefix="school-zuid-member", roles=[SCHOOL_ZUID_GID])

    assert seeded_rbac.has_permission(board_member.gid, process.gid, "read")
    assert not seeded_rbac.has_permission(board_member.gid, process.gid, "write")

    assert seeded_rbac.has_permission(school_noord_member.gid, process.gid, "read")
    assert not seeded_rbac.has_permission(school_noord_member.gid, process.gid, "write")

    assert not seeded_rbac.has_permission(school_zuid_member.gid, process.gid, "read")
    assert not seeded_rbac.has_permission(school_zuid_member.gid, process.gid, "write")


def test_team_members_cannot_access_other_teams_processes(
    admin_backend: DecisionProcessBackend,
    seeded_rbac: AuthRbac,
    auth_user_factory: t.Callable[..., AuthUser],
) -> None:
    """Team membership grants access to its own processes, but not another team's."""
    first_team = admin_backend.create_team(location_gid=VESTIGING_CENTRUM_GID, name="Vakgroep Frans")
    second_team = admin_backend.create_team(location_gid=VESTIGING_CENTRUM_GID, name="Vakgroep Duits")
    first_process = admin_backend.create_process(first_team.gid, "2026-2027")
    second_process = admin_backend.create_process(second_team.gid, "2026-2027")
    first_team_member = auth_user_factory(prefix="first-team-member", roles=[first_team.gid])

    assert seeded_rbac.has_permission(first_team_member.gid, SCHOOL_NOORD_GID, "read")
    assert seeded_rbac.has_permission(first_team_member.gid, first_process.gid, "read")
    assert seeded_rbac.has_permission(first_team_member.gid, first_process.gid, "write")
    assert not seeded_rbac.has_permission(first_team_member.gid, second_process.gid, "read")
    assert not seeded_rbac.has_permission(first_team_member.gid, second_process.gid, "write")


def test_rbac_backfill_removes_legacy_team_location_inheritance(
    admin_backend: DecisionProcessBackend,
    db_per_file: DatabaseContext,
    seeded_rbac: AuthRbac,
    auth_user_factory: t.Callable[..., AuthUser],
) -> None:
    """The backfill removes sibling-team access caused by legacy location membership."""
    first_team = admin_backend.create_team(location_gid=VESTIGING_CENTRUM_GID, name="Vakgroep Biologie")
    second_team = admin_backend.create_team(location_gid=VESTIGING_CENTRUM_GID, name="Vakgroep Scheikunde")
    first_process = admin_backend.create_process(first_team.gid, "2026-2027")
    second_process = admin_backend.create_process(second_team.gid, "2026-2027")
    first_team_member = auth_user_factory(prefix="first-team-member", roles=[first_team.gid])
    board_member = auth_user_factory(prefix="board-member", roles=[BOARD_GID])
    school_member = auth_user_factory(prefix="school-member", roles=[SCHOOL_NOORD_GID])

    seeded_rbac.add_membership(first_team.gid, VESTIGING_CENTRUM_GID)
    seeded_rbac.add_membership(second_team.gid, VESTIGING_CENTRUM_GID)
    assert seeded_rbac.has_permission(first_team_member.gid, second_process.gid, "read")

    backfill_organisation_rbac_permissions_v2(db_per_file)

    assert seeded_rbac.has_permission(board_member.gid, first_process.gid, "read")
    assert not seeded_rbac.has_permission(board_member.gid, first_process.gid, "write")
    assert seeded_rbac.has_permission(school_member.gid, first_process.gid, "read")
    assert not seeded_rbac.has_permission(school_member.gid, first_process.gid, "write")
    assert seeded_rbac.has_permission(first_team_member.gid, first_process.gid, "write")
    assert not seeded_rbac.has_permission(first_team_member.gid, second_process.gid, "read")


def test_grant_process_permissions_is_idempotent(
    admin_backend: DecisionProcessBackend,
    seeded_rbac: AuthRbac,
    auth_user_factory: t.Callable[..., AuthUser],
) -> None:
    """Re-granting must not raise, so a backfill can run over existing processes."""
    team = admin_backend.create_team(location_gid=VESTIGING_CENTRUM_GID, name="Vakgroep Aardrijkskunde")
    process = admin_backend.create_process(team.gid, "2026-2027")

    admin_backend.grant_process_permissions(process, team)

    team_member = auth_user_factory(prefix="team-member", roles=[team.gid])
    assert seeded_rbac.has_permission(team_member.gid, process.gid, "write")
