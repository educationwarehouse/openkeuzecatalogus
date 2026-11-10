"""Organisation relation and RBAC orchestration."""

import typing as t

from endow import Domain

from shared_code.data_model import (
    AuthUser,
    DecisionProcess,
    DecisionProcessNote,
    DecisionProcessNoteEd,
    DecisionTeam,
    DecisionTeamEd,
    Organisation,
    OrganisationEd,
    OrganisationType,
    Tagged,
    TaggedEd,
    update_effectivedated,
)
from shared_code.data_model.constants import Predicate
from shared_code.modules.auth import AuthContext
from shared_code.modules.organisations.policy import OrganisationPolicy
from shared_code.services.applog import Applogger
from shared_code.util.email import extract_email_domain

if t.TYPE_CHECKING:
    from shared_code.infra.database import DatabaseContext


class OrganisationBackend(Domain):
    """Organisation relationship and RBAC permission flows."""

    db: DatabaseContext
    auth: AuthContext
    policy: OrganisationPolicy
    applog: Applogger

    def _archive_actor(self) -> str:
        self.policy.require_manage_relations()
        actor = self.auth.get_email() or self.auth.id
        assert actor, "An admin or service actor must have an identifier"
        return actor

    def _log_archived_processes(self, processes: list[DecisionProcess]) -> None:
        """Record committed process deactivations caused by organisation archival."""
        for process in processes:
            self.applog.try_fire(
                {
                    "kind": "event",
                    "action": "decision_process_archived",
                    "user_gid": self.auth.id,
                    "related": process.gid,
                    "details": {
                        "process_gid": process.gid,
                        "team_gid": process.team_gid,
                        "process_stage": process.process_stage,
                        "reason": "team_archived",
                    },
                }
            )

    def _archive_team(self, team_gid: str, actor: str) -> list[DecisionProcess]:
        if not DecisionTeam.where(gid=team_gid).exists():
            raise ValueError("Vakgroep niet gevonden.")

        process_query = DecisionProcess.where(team_gid=team_gid, active=True)
        processes = process_query.collect()

        process_query.update(active=False)
        update_effectivedated(self.db, DecisionTeamEd, DecisionTeamEd.gid == team_gid, last_saved_by=actor, delete=True)

        return list(processes)

    def archive_team(self, team_gid: str) -> None:
        """Archive a teaching team and close its decision processes."""
        actor = self._archive_actor()
        processes = self._archive_team(team_gid, actor)
        self.db.commit()

        self._log_archived_processes(processes)

    def _archive_location(self, location_gid: str, actor: str) -> list[DecisionProcess]:
        location = Organisation.where(gid=location_gid).first()
        if not location or location.organisation_type != OrganisationType.LOCATION:
            raise ValueError("Vestiging niet gevonden.")

        processes = []
        for team_gid in DecisionTeam.where(location_gid=location_gid).column(DecisionTeam.gid):
            processes.extend(self._archive_team(team_gid, actor))

        for note_gid in DecisionProcessNote.where(organisation_gid=location_gid).column(DecisionProcessNote.gid):
            update_effectivedated(
                self.db, DecisionProcessNoteEd, DecisionProcessNoteEd.gid == note_gid, last_saved_by=actor, delete=True
            )

        for relation_gid in Tagged.where(
            (Tagged.object_gid == location_gid) & (Tagged.predicate == Predicate.IS_SCHOOL_OF)
        ).column(Tagged.gid):
            update_effectivedated(self.db, TaggedEd, TaggedEd.gid == relation_gid, last_saved_by=actor, delete=True)

        update_effectivedated(
            self.db, OrganisationEd, OrganisationEd.gid == location_gid, last_saved_by=actor, delete=True
        )
        return processes

    def archive_location(self, location_gid: str) -> None:
        """Archive a location and its teaching teams."""
        actor = self._archive_actor()
        if len(set(self.schools_for_location(location_gid))) > 1:
            raise ValueError("Een gedeelde vestiging kan niet worden verwijderd.")
        processes = self._archive_location(location_gid, actor)
        self.db.commit()

        self._log_archived_processes(processes)

    def _archive_school(self, school_gid: str, actor: str) -> list[DecisionProcess]:
        school = Organisation.where(gid=school_gid).first()
        if not school or school.organisation_type != OrganisationType.SCHOOL:
            raise ValueError("School niet gevonden.")

        processes = []
        for location_gid in set(self.locations_for_school(school_gid)):
            if len(set(self.schools_for_location(location_gid))) > 1:
                raise ValueError("Een gedeelde vestiging kan niet samen met deze school worden verwijderd.")
            processes.extend(self._archive_location(location_gid, actor))

        for note_gid in DecisionProcessNote.where(organisation_gid=school_gid).column(DecisionProcessNote.gid):
            update_effectivedated(
                self.db, DecisionProcessNoteEd, DecisionProcessNoteEd.gid == note_gid, last_saved_by=actor, delete=True
            )

        relation_gids = Tagged.where(
            ((Tagged.subject_gid == school_gid) & (Tagged.predicate == Predicate.IS_SCHOOL_OF))
            | ((Tagged.object_gid == school_gid) & (Tagged.predicate == Predicate.IS_BOARD_OF))
        ).column(Tagged.gid)
        for relation_gid in relation_gids:
            update_effectivedated(self.db, TaggedEd, TaggedEd.gid == relation_gid, last_saved_by=actor, delete=True)

        update_effectivedated(
            self.db, OrganisationEd, OrganisationEd.gid == school_gid, last_saved_by=actor, delete=True
        )
        return processes

    def archive_school(self, school_gid: str) -> None:
        """Archive a school and its locations, teams, processes, notes, and relations."""
        actor = self._archive_actor()
        processes = self._archive_school(school_gid, actor)
        self.db.commit()

        self._log_archived_processes(processes)

    def archive_board(self, board_gid: str) -> None:
        """Archive a board and its exclusively owned school hierarchy."""
        actor = self._archive_actor()
        board = Organisation.where(gid=board_gid).first()
        if not board or board.organisation_type != OrganisationType.BOARD:
            raise ValueError("Bestuur niet gevonden.")

        processes = []
        for school_gid in set(self.schools_for_board(board_gid)):
            if len(set(self.boards_for_school(school_gid))) > 1:
                raise ValueError("Een gedeelde school kan niet samen met dit bestuur worden verwijderd.")
            processes.extend(self._archive_school(school_gid, actor))

        for note_gid in DecisionProcessNote.where(organisation_gid=board_gid).column(DecisionProcessNote.gid):
            update_effectivedated(
                self.db, DecisionProcessNoteEd, DecisionProcessNoteEd.gid == note_gid, last_saved_by=actor, delete=True
            )
        update_effectivedated(
            self.db, OrganisationEd, OrganisationEd.gid == board_gid, last_saved_by=actor, delete=True
        )
        self.db.commit()

        self._log_archived_processes(processes)

    def get_organisation(self, organisation_gid: str) -> Organisation:
        """Load one organisation by its stable identifier."""
        return Organisation.where(gid=organisation_gid).first_or_fail(ValueError("Organisatie niet gevonden."))

    def visible_organisations(
        self,
        organisation_type: OrganisationType,
        privilege: str = "read",
    ) -> list[Organisation]:
        """Return the organisations of one type the actor may reach, by name.

        Only `gid` and `name` are loaded, enough for membership listings and dropdowns. See
        `OrganisationPolicy.organisation_query` for why this scope is not `request_read`.
        """
        return list(
            self.policy.organisation_query(organisation_type, privilege).select(
                Organisation.gid,
                Organisation.name,
                orderby=Organisation.name,
            )
        )

    def boards_for_school(self, school_gid: str) -> list[str]:
        """Return boards connected to a school."""
        # public info -> no policy
        return Tagged.lookup(None, Predicate.IS_BOARD_OF, school_gid)

    def board_for_school(self, school_gid: str) -> Organisation:
        """Return the board connected to one school."""
        board_gids = self.boards_for_school(school_gid)
        if len(board_gids) != 1:
            raise ValueError("Bestuur niet gevonden.")

        return Organisation.where(gid=board_gids[0]).first_or_fail(ValueError("Bestuur niet gevonden."))

    def locations_for_school(self, school_gid: str) -> list[str]:
        """Return locations connected to a school."""
        # public info -> no policy
        return Tagged.lookup(school_gid, Predicate.IS_SCHOOL_OF, None)

    def schools_for_location(self, location_gid: str) -> list[str]:
        """Return schools connected to a location."""
        # public info -> no policy
        return Tagged.lookup(None, Predicate.IS_SCHOOL_OF, location_gid)

    def school_for_location(self, location_gid: str) -> Organisation:
        """Return the school connected to one location."""
        school_gids = self.schools_for_location(location_gid)
        if len(school_gids) != 1:
            raise ValueError("School niet gevonden.")

        return Organisation.where(gid=school_gids[0]).first_or_fail(ValueError("School niet gevonden."))

    def schools_for_board(self, board_gid: str) -> list[str]:
        """Return schools connected to a board."""
        # public info -> no policy
        return Tagged.lookup(board_gid, Predicate.IS_BOARD_OF, None)

    def connect_board_to_school(self, board_gid: str, school_gid: str) -> None:
        """Create a board-school relation and grant the implied permissions."""
        self.policy.require_manage_relations()
        rbac = self.auth.raw_rbac
        last_saved_by = self.auth.get_email() or self.auth.id
        assert last_saved_by, "Admin user or service should always have an email or identifier"

        Tagged.insert_relation_if_missing(
            board_gid,
            Predicate.IS_BOARD_OF,
            school_gid,
            comment="connect_board_to_school",
            last_saved_by=last_saved_by,
        )

        own_location_gids = self.locations_for_school(school_gid)

        rbac.add_permissions(board_gid, school_gid, ["read", "invite"])
        rbac.add_permission(school_gid, board_gid, "read")

        for location_gid in own_location_gids:
            rbac.add_permission(board_gid, location_gid, "read")
            rbac.add_permission(school_gid, location_gid, "*")
            rbac.add_permission(location_gid, board_gid, "read")

        self.db.commit()

    def connect_school_to_location(self, school_gid: str, location_gid: str) -> None:
        """Create a school-location relation and grant the implied permissions."""
        self.policy.require_manage_relations()
        last_saved_by = self.auth.get_email() or self.auth.id
        assert last_saved_by, "Admin user or service should always have an email or identifier"

        rbac = self.auth.raw_rbac
        Tagged.insert_relation_if_missing(
            school_gid,
            Predicate.IS_SCHOOL_OF,
            location_gid,
            comment="connect_school_to_location",
            last_saved_by=last_saved_by,
        )

        rbac.add_permission(school_gid, location_gid, "*")

        for board_gid in self.boards_for_school(school_gid):
            rbac.add_permission(board_gid, location_gid, "read")
            rbac.add_permission(location_gid, board_gid, "read")

        self.db.commit()

    @classmethod
    def _find_org_by_email_domain(cls, email: str | None) -> Organisation | None:
        """Return the organisation matching the normalized email domain, if any."""
        if not (domain := extract_email_domain(email)):
            return None

        return Organisation.where(Organisation.email_domains.contains(domain)).first()

    def grant_memberships(self, user: AuthUser) -> None:
        """Grant the matching organisation membership for a user email, if any."""
        if not user.gid:
            return None

        org = self._find_org_by_email_domain(user.email)

        if not org:
            return None

        return self.auth.add_membership(user.gid, org.gid)
