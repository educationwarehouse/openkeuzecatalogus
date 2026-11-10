"""Migration support manager for `organisation_model`."""

from collections import defaultdict

from edwh_auth_rbac import AuthRbac
from edwh_migrate import ViewMigrationManager
from typedal import TypeDAL

from .core import (
    create_effdted_model_view_with_prio_v4,
    drop_table_or_mv,
    simple_progress,
    upsert_index_v1,
)


# noinspection PyPep8Naming
class OrganisationModelWithPrio_V1(ViewMigrationManager):
    """Manage create/drop operations for the prioritized organisation model view."""

    uses = ()

    since = "create_organisation_ed_20260622_001"

    def up(self) -> None:
        """Create view/index objects for the organisation model."""
        create_effdted_model_view_with_prio_v4(self.db, "organisation")
        upsert_index_v1(
            self.db,
            "organisation_model",
            ["gid"],
            include=["name", "short_name", "organisation_type"],
            unique=True,
        )
        upsert_index_v1(
            self.db,
            "organisation_model",
            ["organisation_type", "name"],
            include=["gid", "short_name"],
        )

    def down(self) -> None:
        """Drop view/index objects for the organisation model."""
        self.db.executesql("""
        DROP TRIGGER IF EXISTS refresh_organisation_model_trigger ON organisation_ed;
        DROP TRIGGER IF EXISTS organisation_model_update_trigger ON organisation_ed;
        """)

        self.db.executesql("""
        DROP FUNCTION IF EXISTS get_active_organisation(uuid);
        DROP FUNCTION IF EXISTS apply_change_organisation_model();
        DROP FUNCTION IF EXISTS rebuild_organisation_model();
        """)
        drop_table_or_mv(self.db, "organisation_model")


def backfill_organisation_rbac_identities_v1(db: TypeDAL) -> None:
    """Ensure every organisation has a matching RBAC identity and type membership."""
    rbac = AuthRbac(db)
    rbac.define_model(allowed_types=["user", "group", "item"], redefine=True, migrate=False)

    rows = db.executesql(
        """
        SELECT gid, name, organisation_type
        FROM organisation_model
        ORDER BY organisation_type, name, id
        """,
        colnames=("gid", "name", "organisation_type"),
    )

    for organisation in simple_progress(rows, every=1000):
        rbac.add_group(
            f"{organisation['gid']}@organisation",
            organisation["name"],
            [],
            # note: this member_of used to have
            #  e.g. board@internal etc but that makes the recursive membership explode
            gid=organisation["gid"],
            allow_existing=True,
        )
        rbac.add_permission(organisation["gid"], organisation["gid"], "*")


def _grant_board_hierarchy_permissions_v1(
    rbac: AuthRbac, board_gid: str, school_gids: list[str], school_locations: defaultdict[str, list[str]]
) -> None:
    """Grant hierarchy access and read access to sibling schools' locations."""
    board_location_gids: list[str] = []
    for school_gid in school_gids:
        rbac.add_permission(board_gid, school_gid, "*")
        for location_gid in school_locations[school_gid]:
            rbac.add_permission(board_gid, location_gid, "*")
            rbac.add_permission(school_gid, location_gid, "*")
            rbac.add_permission(location_gid, board_gid, "read")
            board_location_gids.append(location_gid)

    for school_gid in school_gids:
        own_location_gids = set(school_locations[school_gid])
        for location_gid in board_location_gids:
            if location_gid in own_location_gids:
                continue
            rbac.add_permission(school_gid, location_gid, "read")


def backfill_organisation_rbac_permissions_v1(db: TypeDAL) -> None:
    """Replace seeded org-to-org hierarchy RBAC with explicit permissions."""
    rbac = AuthRbac(db)
    rbac.define_model(allowed_types=["user", "group", "item"], redefine=True, migrate=False)

    organisation_rows = db.executesql(
        """
        SELECT gid
        FROM organisation_model
        """,
        colnames=("gid",),
    )
    board_school_rows = db.executesql(
        """
        SELECT subject_gid, object_gid
        FROM tagged_model
        WHERE predicate = 'IS_BOARD_OF'
        """,
        colnames=("subject_gid", "object_gid"),
    )
    school_location_rows = db.executesql(
        """
        SELECT subject_gid, object_gid
        FROM tagged_model
        WHERE predicate = 'IS_SCHOOL_OF'
        """,
        colnames=("subject_gid", "object_gid"),
    )
    organisation_gids = [row["gid"] for row in organisation_rows]
    board_schools = defaultdict[str, list[str]](list)
    school_locations = defaultdict[str, list[str]](list)

    for row in board_school_rows:
        board_schools[str(row["subject_gid"])].append(str(row["object_gid"]))

    for row in school_location_rows:
        school_locations[str(row["subject_gid"])].append(str(row["object_gid"]))

    db.executesql(
        """
        DELETE FROM membership
        WHERE subject IN (SELECT gid FROM organisation_model)
          AND member_of IN (SELECT gid FROM organisation_model)
        """,
    )
    db.executesql(
        """
        DELETE FROM permission
        WHERE identity_object_id IN (SELECT gid FROM organisation_model)
          AND target_object_id IN (SELECT gid FROM organisation_model)
          AND identity_object_id <> target_object_id
        """,
    )
    for organisation_gid in organisation_gids:
        rbac.add_permission(organisation_gid, organisation_gid, "*")

    for board_gid, school_gids in board_schools.items():
        _grant_board_hierarchy_permissions_v1(rbac, board_gid, school_gids, school_locations)


def _backfill_process_permissions_v2(
    db: TypeDAL,
    rbac: AuthRbac,
    school_locations: dict[str, list[str]],
    boards_by_school: dict[str, list[str]],
) -> None:
    """Restore explicit board, school, and team process grants."""
    team_rows = db.executesql(
        """
        SELECT gid, location_gid
        FROM decision_team_model
        """,
        colnames=("gid", "location_gid"),
    )
    process_rows = db.executesql(
        """
        SELECT gid, team_gid
        FROM decision_process
        """,
        colnames=("gid", "team_gid"),
    )
    schools_by_location = {
        location_gid: school_gid
        for school_gid, location_gids in school_locations.items()
        for location_gid in location_gids
    }
    locations_by_team = {str(row["gid"]): str(row["location_gid"]) for row in team_rows}

    for process in process_rows:
        process_gid = str(process["gid"])
        team_gid = str(process["team_gid"])
        school_gid = schools_by_location.get(locations_by_team.get(team_gid, ""))
        if not school_gid:
            continue

        for board_gid in boards_by_school[school_gid]:
            rbac.add_permission(board_gid, process_gid, "read")

        rbac.add_permission(school_gid, process_gid, "read")
        rbac.add_permissions(team_gid, process_gid, "*")
        rbac.add_permission(team_gid, school_gid, "read")


def backfill_organisation_rbac_permissions_v2(db: TypeDAL) -> None:
    """Align organisation grants with the decision-maker read-only board model."""
    rbac = AuthRbac(db)
    rbac.define_model(allowed_types=["user", "group", "item"], redefine=True, migrate=False)

    organisation_rows = db.executesql(
        """
        SELECT gid
        FROM organisation_model
        """,
        colnames=("gid",),
    )
    board_school_rows = db.executesql(
        """
        SELECT subject_gid, object_gid
        FROM tagged_model
        WHERE predicate = 'IS_BOARD_OF'
        """,
        colnames=("subject_gid", "object_gid"),
    )
    school_location_rows = db.executesql(
        """
        SELECT subject_gid, object_gid
        FROM tagged_model
        WHERE predicate = 'IS_SCHOOL_OF'
        """,
        colnames=("subject_gid", "object_gid"),
    )
    organisation_gids = [row["gid"] for row in organisation_rows]
    board_schools = defaultdict[str, list[str]](list)
    school_locations = defaultdict[str, list[str]](list)
    boards_by_school = defaultdict[str, list[str]](list)

    for row in board_school_rows:
        board_gid = str(row["subject_gid"])
        school_gid = str(row["object_gid"])
        board_schools[board_gid].append(school_gid)
        boards_by_school[school_gid].append(board_gid)

    for row in school_location_rows:
        school_locations[str(row["subject_gid"])].append(str(row["object_gid"]))

    db.executesql(
        """
        DELETE FROM membership
        WHERE subject IN (SELECT gid FROM organisation_model)
          AND member_of IN (SELECT gid FROM organisation_model)
        """,
    )
    db.executesql(
        """
        DELETE FROM permission
        WHERE identity_object_id IN (SELECT gid FROM organisation_model)
          AND target_object_id IN (SELECT gid FROM organisation_model)
          AND identity_object_id <> target_object_id
        """,
    )
    db.executesql(
        """
        DELETE FROM permission
        WHERE identity_object_id IN (
            SELECT gid
            FROM organisation_model
            WHERE organisation_type = 'location'
        )
          AND target_object_id IN (SELECT gid FROM decision_team_model)
        """,
    )
    db.executesql(
        """
        DELETE FROM membership
        WHERE subject IN (SELECT gid FROM decision_team_model)
          AND member_of IN (
              SELECT gid
              FROM organisation_model
              WHERE organisation_type = 'location'
          )
        """,
    )

    for organisation_gid in organisation_gids:
        rbac.add_permission(organisation_gid, organisation_gid, "*")

    for board_gid, school_gids in board_schools.items():
        for school_gid in school_gids:
            rbac.add_permissions(board_gid, school_gid, ["read", "invite"])
            rbac.add_permission(school_gid, board_gid, "read")

            for location_gid in school_locations[school_gid]:
                rbac.add_permission(board_gid, location_gid, "read")
                rbac.add_permission(school_gid, location_gid, "*")
                rbac.add_permission(location_gid, board_gid, "read")

    _backfill_process_permissions_v2(db, rbac, school_locations, boards_by_school)
