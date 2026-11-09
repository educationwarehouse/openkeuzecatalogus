"""Integration coverage for the guided decision-process lifecycle.

`test_decision_process_rbac` pins the permission graph. This module exercises the
state-changing backend methods that the wizard controllers call, using the same migrated
organisation hierarchy. It deliberately avoids the invite flow, which is covered elsewhere.
"""

import typing as t
import uuid

import pytest

from shared_code.data_model import AuthUser, DecisionTeam, DecisionTeamEd
from shared_code.data_model.constants import get_themes
from shared_code.infra.database import DatabaseContext
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.auth.contract import AuthActor, edwh_rbac_adapter
from shared_code.modules.decision_processes import DecisionProcessBackend
from shared_code.tests.applog import RecordingApplogger
from shared_code.util.olid import generate as generate_olid

BOARD_GID = "dc0874bb-0901-406b-8567-c646e61eeb3b"
SCHOOL_NOORD_GID = "9f5788bd-d8c5-428c-b61e-0b980733275b"
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


@pytest.fixture()
def user_backend_factory(db_per_file: DatabaseContext) -> t.Callable[[AuthUser], DecisionProcessBackend]:
    """Build a backend for one user with the real RBAC adapter."""

    def create(user: AuthUser) -> DecisionProcessBackend:
        actor = AuthActor(kind="user", id=user.gid, email=user.email, name=user.full_name)
        adapter = edwh_rbac_adapter(
            get_actor=lambda: actor,
            get_rbac=lambda ctx: ctx.raw_rbac,
        )
        return DecisionProcessBackend.with_injected(db=db_per_file, auth_adapter=adapter)

    return create


def _make_team(
    backend: DecisionProcessBackend,
    name: str,
    courses: list[str] | None = None,
    levels: list[str] | None = None,
    years: list[str] | None = None,
) -> DecisionTeam:
    """Create a team below the shared Vestiging Centrum fixture."""
    return backend.create_team(
        VESTIGING_CENTRUM_GID,
        name,
        courses=courses,
        levels=levels,
        years=years,
    )


def test_create_team_rejects_unknown_location(admin_backend: DecisionProcessBackend) -> None:
    """A team must hang below an existing location."""
    with pytest.raises(ValueError, match="Vestiging niet gevonden"):
        admin_backend.create_team(str(uuid.uuid4()), "Ghost Team")


def test_create_process_rejects_unknown_team(admin_backend: DecisionProcessBackend) -> None:
    """A process must belong to an existing team."""
    with pytest.raises(ValueError, match="Vakgroep niet gevonden"):
        admin_backend.create_process(str(uuid.uuid4()), "2026-2027")


def test_unregistered_team_is_not_offered_for_starting_a_process(
    admin_backend: DecisionProcessBackend,
) -> None:
    """Teams with missing ownership records must not appear in the start dropdown."""
    registered = _make_team(admin_backend, "Klassieke Talen Bovenbouw")
    missing_group = DecisionTeamEd.insert(
        location_gid=VESTIGING_CENTRUM_GID,
        name=registered.name,
        last_saved_by="pytest/import",
    )
    missing_location = DecisionTeamEd.insert(
        location_gid=str(uuid.uuid4()),
        name=registered.name,
        last_saved_by="pytest/import",
    )
    assert missing_group is not None and missing_location is not None

    visible_gids = {team.gid for team in admin_backend.visible_teams("write")}

    assert registered.gid in visible_gids
    assert missing_group.gid not in visible_gids
    assert missing_location.gid not in visible_gids


def test_create_process_copies_team_criteria(admin_backend: DecisionProcessBackend) -> None:
    """A new process starts from the team's criteria and has no leader until fase 1."""
    team = _make_team(
        admin_backend,
        "Criteria Team",
        courses=["Rekenen"],
        levels=["Havo"],
        years=["Leerjaar 1"],
    )

    process = admin_backend.create_process(team.gid, "2026-2027")

    assert list(process.courses) == ["Rekenen"]
    assert list(process.levels) == ["Havo"]
    assert list(process.years) == ["Leerjaar 1"]
    assert process.project_leader_gid is None


def test_process_visibility_filters_and_archive_lifecycle(
    admin_backend: DecisionProcessBackend,
) -> None:
    """Active/archived visibility and archive/reopen behaviour stay aligned."""
    team = _make_team(admin_backend, "Lifecycle Team")
    active = admin_backend.create_process(team.gid, "2026-2027")
    archived = admin_backend.create_process(team.gid, "2025-2026")

    admin_backend.archive_process(archived.gid)

    active_gids = {process.gid for process in admin_backend.list_visible_processes()}
    assert active.gid in active_gids
    assert archived.gid not in active_gids

    all_gids = {process.gid for process in admin_backend.list_visible_processes(include_archived=True)}
    assert {active.gid, archived.gid}.issubset(all_gids)
    assert admin_backend.count_visible_archived_processes() == 1
    assert admin_backend.writable_process_gids(set()) == set()
    assert admin_backend.writable_process_gids({active.gid, archived.gid}) == {active.gid, archived.gid}
    assert {process.gid for process in admin_backend.team_processes(team.gid)} == {active.gid, archived.gid}

    reopened = admin_backend.reopen_process(archived.gid)
    assert reopened.active is True
    assert reopened.process_stage == "team"


def test_reopen_process_rejection_is_logged(
    admin_backend: DecisionProcessBackend,
    auth_user_factory: t.Callable[..., AuthUser],
    db_per_file: DatabaseContext,
) -> None:
    """A team member's rejected reopening attempt produces an audit event."""
    team = _make_team(admin_backend, "Reopen Audit Team")
    process = admin_backend.create_process(team.gid, "2026-2027")
    admin_backend.complete_process(process.gid)
    member = auth_user_factory(prefix="reopen-member", roles=[team.gid])
    actor = AuthActor(kind="user", id=member.gid, email=member.email, name=member.full_name)
    auth_adapter = edwh_rbac_adapter(
        get_actor=lambda: actor,
        get_rbac=lambda ctx: ctx.raw_rbac,
    )
    applog = RecordingApplogger.with_injected(db=db_per_file, auth_adapter=auth_adapter)
    member_backend = DecisionProcessBackend.with_injected(
        db=db_per_file,
        auth_adapter=auth_adapter,
        applog=applog,
    )

    with pytest.raises(ValueError, match="projectleider"):
        member_backend.reopen_process(process.gid)

    event = applog.fired_events[-1]
    assert event["kind"] == "event"
    assert event["action"] == "decision_process_reopen_denied"
    assert event["user_gid"] == member.gid
    assert event["related"] == process.gid
    assert event["details"] == {
        "process_gid": process.gid,
        "team_gid": team.gid,
        "process_stage": "done",
    }
    assert admin_backend.get_process(process.gid).process_stage == "done"


def test_complete_process_sets_done_and_rejects_unknown_stage(
    admin_backend: DecisionProcessBackend,
) -> None:
    """Completion is a stage transition, and unknown stages are rejected."""
    team = _make_team(admin_backend, "Completion Team")
    process = admin_backend.create_process(team.gid, "2026-2027")

    completed = admin_backend.complete_process(process.gid)
    assert completed.process_stage == "done"

    with pytest.raises(ValueError, match="Onbekende procesfase"):
        admin_backend.set_stage(process.gid, "maybe")


def test_project_leader_reopens_completed_process_without_losing_criteria(
    admin_backend: DecisionProcessBackend,
    auth_user_factory: t.Callable[..., AuthUser],
    user_backend_factory: t.Callable[[AuthUser], DecisionProcessBackend],
) -> None:
    """A real team leader can reopen completed work and retains the saved criteria."""
    team = _make_team(admin_backend, "Leader reopening team", courses=["Rekenen"], levels=["Havo"])
    process = admin_backend.create_process(team.gid, "2026-2027")
    leader = auth_user_factory(prefix="reopening-leader", roles=[team.gid])
    admin_backend.update_project_leader(process.gid, leader.gid)
    admin_backend.complete_process(process.gid)
    leader_backend = user_backend_factory(leader)
    reopened = leader_backend.reopen_process(process.gid)
    assert reopened.active is True
    assert reopened.process_stage == "team"
    assert reopened.courses == ["Rekenen"]
    assert reopened.levels == ["Havo"]
    assert reopened.project_leader_gid == leader.gid
    assert leader_backend.may_edit_criteria(process.gid)
    leader_backend.update_criteria(process.gid, courses=["Engels"], levels=["Vwo"], years=[])
    assert admin_backend.get_process(process.gid).courses == ["Engels"]


def test_list_context_batches_team_school_and_leader(
    admin_backend: DecisionProcessBackend,
    auth_user_factory: t.Callable[..., AuthUser],
) -> None:
    """The canvas context maps resolve team, school, and leader without per-row lookups."""
    team = _make_team(admin_backend, "Context Team")
    leader = auth_user_factory(prefix="context-leader", roles=[team.gid])
    process = admin_backend.create_process(team.gid, "2026-2027")
    admin_backend.update_project_leader(process.gid, leader.gid)
    process = admin_backend.get_process(process.gid)

    context = admin_backend.list_context([process])

    assert context["teams_by_gid"][team.gid].name == "Context Team"
    assert context["school_gid_by_location_gid"][team.location_gid] == SCHOOL_NOORD_GID
    assert context["project_leaders_by_gid"][leader.gid].full_name == leader.full_name


def test_update_project_leader_rejects_non_member(
    admin_backend: DecisionProcessBackend,
    auth_user_factory: t.Callable[..., AuthUser],
) -> None:
    """Only team members can be selected as project leader."""
    team = _make_team(admin_backend, "Leader Team")
    process = admin_backend.create_process(team.gid, "2026-2027")
    outsider = auth_user_factory(prefix="leader-outsider")

    with pytest.raises(ValueError, match="projectleider"):
        admin_backend.update_project_leader(process.gid, outsider.gid)

    admin_backend.update_project_leader(process.gid, None)
    assert admin_backend.get_process(process.gid).project_leader_gid is None


def test_update_criteria_and_may_edit_criteria(
    admin_backend: DecisionProcessBackend,
    auth_user_factory: t.Callable[..., AuthUser],
    user_backend_factory: t.Callable[[AuthUser], DecisionProcessBackend],
) -> None:
    """Criteria updates persist, and editability is reserved for the leader or admin."""
    team = _make_team(admin_backend, "Criteria Guard Team")
    member = auth_user_factory(prefix="criteria-member", roles=[team.gid])
    process = admin_backend.create_process(team.gid, "2026-2027")

    updated = admin_backend.update_criteria(
        process.gid,
        courses=["Rekenen"],
        levels=["Havo"],
        years=["Leerjaar 1"],
    )

    assert list(updated.courses) == ["Rekenen"]
    assert list(updated.levels) == ["Havo"]
    assert list(updated.years) == ["Leerjaar 1"]
    assert admin_backend.may_edit_criteria(process.gid) is True
    assert user_backend_factory(member).may_edit_criteria(process.gid) is False


def test_theme_visions_and_save_vision(admin_backend: DecisionProcessBackend) -> None:
    """Theme summaries are created, ordered, and snapshotted into the process vision."""
    team = _make_team(admin_backend, "Vision Team")
    process = admin_backend.create_process(team.gid, "2026-2027")

    visions = admin_backend.ensure_theme_visions(process.gid)
    assert len(visions) == len(get_themes())

    first_theme, first_vision = next(iter(visions.items()))
    admin_backend.update_theme_summary(process.gid, first_vision.gid, first_theme, "Eerste samenvatting")

    ordered = admin_backend.theme_visions(process.gid)
    assert ordered[0].theme == first_theme
    assert ordered[0].summary == "Eerste samenvatting"

    second_theme = next(theme for theme in visions if theme != first_theme)
    second_vision = visions[second_theme]
    admin_backend.update_priorities(
        process.gid,
        {
            first_vision.gid: ["Hoogste prioriteit"],
            second_vision.gid: [],
        },
    )
    reprioritised = {vision.gid: vision for vision in admin_backend.theme_visions(process.gid)}
    assert reprioritised[first_vision.gid].summary == "Hoogste prioriteit"
    assert reprioritised[first_vision.gid].sort_order == 0
    assert reprioritised[second_vision.gid].summary == ""

    with pytest.raises(ValueError, match="Themasamenvatting niet gevonden"):
        admin_backend.update_priorities(process.gid, {str(uuid.uuid4()): ["Niet opslaan"]})

    saved = admin_backend.save_vision(process.gid)
    assert "Hoogste prioriteit" in saved.vision


def test_guidance_notes_are_shared_and_bulk_created(admin_backend: DecisionProcessBackend) -> None:
    """Board and school guidance is organisation-scoped and created on demand."""
    team = _make_team(admin_backend, "Guidance Team")
    process = admin_backend.create_process(team.gid, "2026-2027")
    theme = next(iter(get_themes()))

    with pytest.raises(ValueError, match="Notitie niet gevonden"):
        admin_backend.get_guidance_note(process.gid, "board", theme)

    note = admin_backend.get_guidance_note(process.gid, "board", theme, writable=True)
    assert note.theme == theme

    admin_backend.update_guidance_note(process.gid, "board", theme, "Bestuurskader")
    assert admin_backend.guidance_notes(process.gid)["board"][theme].content == "Bestuurskader"

    ensured = admin_backend.guidance_notes(process.gid, ensure_for_writers=True)
    assert set(ensured["board"]) == set(get_themes())
    assert set(ensured["school"]) == set(get_themes())


def test_material_selection_and_pros_cons_flow(admin_backend: DecisionProcessBackend) -> None:
    """Material selections and their pros/cons survive add, update, clone, and remove."""
    team = _make_team(admin_backend, "Pros Cons Team")
    process = admin_backend.create_process(team.gid, "2026-2027")

    plus_olid = generate_olid("product", "OLID-123")
    weg_olid = generate_olid("product", "OLID-456")
    admin_backend.change_material_selection(process.gid, "add", "bought", "Methode Plus", plus_olid)
    admin_backend.change_material_selection(process.gid, "add", "bought", "Methode Weg", weg_olid)
    admin_backend.change_material_selection(process.gid, "add", "bought", "Methode Plus hernoemd", plus_olid)
    selections = admin_backend.material_selections(process.gid)
    assert {selection.name for selection in selections} == {"Methode Plus hernoemd", "Methode Weg"}

    admin_backend.change_material_selection(process.gid, "remove", "bought", "", weg_olid)
    selections = admin_backend.material_selections(process.gid)
    assert [selection.name for selection in selections] == ["Methode Plus hernoemd"]

    selection = selections[0]
    admin_backend.save_pros_cons(
        process.gid,
        selection.gid,
        pros={"new": ["Duidelijk"]},
        cons={"new": ["Duur"]},
    )

    by_type = admin_backend.pros_and_cons_by_type(process.gid)
    assert len(by_type["pro"]) == 1
    assert len(by_type["con"]) == 1

    by_material = admin_backend.pros_and_cons_by_material_selection(process.gid, {selection.gid})
    assert len(by_material["pro"].get(selection.gid, [])) == 1
    assert len(by_material["con"].get(selection.gid, [])) == 1

    pro_item = by_type["pro"][0]
    admin_backend.update_pros_cons_content(process.gid, pro_item.gid, "Heel duidelijk")
    assert admin_backend.pros_and_cons(process.gid, "pro")[0].content == "Heel duidelijk"

    clone = admin_backend.clone_pros_cons(process.gid, pro_item.gid, 42)
    assert clone.content == "Heel duidelijk"
    assert clone.sort_order == 42

    admin_backend.save_pros_cons(
        process.gid,
        selection.gid,
        pros={pro_item.gid: ["Aangescherpt punt"], "new": ["", "Nieuw punt"]},
        cons={},
    )

    pros = admin_backend.pros_and_cons(process.gid, "pro")
    assert {item.content for item in pros} == {"Aangescherpt punt", "Nieuw punt"}
    assert all(item.content for item in pros)
    assert admin_backend.pros_and_cons(process.gid, "con") == []


def test_assign_theme_moves_items_and_reindexes_source_column(admin_backend: DecisionProcessBackend) -> None:
    """Moving assessments to a theme preserves order in both the destination and source columns."""
    theme = next(iter(get_themes()))
    team = _make_team(admin_backend, "Theme Assignment Team")
    process = admin_backend.create_process(team.gid, "2026-2027")
    admin_backend.change_material_selection(
        process.gid, "add", "bought", "Methode Plus", generate_olid("product", "OLID-123")
    )
    selection = admin_backend.material_selections(process.gid)[0]
    admin_backend.save_pros_cons(
        process.gid,
        selection.gid,
        pros={"first": ["Eerste punt"], "second": ["Tweede punt"], "third": ["Derde punt"]},
        cons={},
    )
    source_items = admin_backend.pros_and_cons(process.gid, "pro")

    admin_backend.assign_theme(
        process.gid,
        item_gids=[source_items[0].gid, source_items[1].gid],
        theme=theme,
        previous_theme=None,
        previous_item_type="pro",
    )

    items_by_content = {item.content: item for item in admin_backend.pros_and_cons(process.gid, "pro")}
    assert items_by_content["Eerste punt"].theme == theme
    assert items_by_content["Tweede punt"].theme == theme
    assert {items_by_content["Eerste punt"].sort_order, items_by_content["Tweede punt"].sort_order} == {0, 1}
    assert items_by_content["Derde punt"].theme is None
    assert items_by_content["Derde punt"].sort_order == 0

    admin_backend.assign_theme(
        process.gid,
        item_gids=[],
        theme=None,
        previous_theme=theme,
        previous_item_type=None,
    )
    assert {item.sort_order for item in admin_backend.pros_and_cons(process.gid, "pro") if item.theme == theme} == {
        0,
        1,
    }

    with pytest.raises(ValueError, match="Onbekende bronkolom"):
        admin_backend.assign_theme(
            process.gid,
            item_gids=[],
            theme=None,
            previous_theme=None,
            previous_item_type=None,
        )
