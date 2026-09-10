"""Organisation relation and RBAC orchestration."""

import typing as t

from endow import Domain

from shared_code.data_model import AuthUser, Organisation, Tagged
from shared_code.data_model.constants import Predicate
from shared_code.modules.auth import AuthContext
from shared_code.modules.organisations.policy import OrganisationPolicy
from shared_code.util.email import extract_email_domain

if t.TYPE_CHECKING:
    from shared_code.infra.database import DatabaseContext


class OrganisationBackend(Domain):
    """Organisation relationship and RBAC permission flows."""

    db: DatabaseContext
    auth: AuthContext
    policy: OrganisationPolicy

    def boards_for_school(self, school_gid: str) -> list[str]:
        """Return boards connected to a school."""
        # public info -> no policy
        return Tagged.lookup(None, Predicate.IS_BOARD_OF, school_gid)

    def locations_for_school(self, school_gid: str) -> list[str]:
        """Return locations connected to a school."""
        # public info -> no policy
        return Tagged.lookup(school_gid, Predicate.IS_SCHOOL_OF, None)

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
        other_school_gids = [gid for gid in self.schools_for_board(board_gid) if gid != school_gid]
        other_location_gids: list[str] = []

        rbac.add_permission(board_gid, school_gid, "*")

        for location_gid in own_location_gids:
            rbac.add_permission(board_gid, location_gid, "*")
            rbac.add_permission(school_gid, location_gid, "*")
            rbac.add_permission(location_gid, board_gid, "read")

        for other_school_gid in other_school_gids:
            other_location_gids.extend(self.locations_for_school(other_school_gid))

        for location_gid in other_location_gids:
            rbac.add_permission(school_gid, location_gid, "read")

        for location_gid in own_location_gids:
            for other_school_gid in other_school_gids:
                rbac.add_permission(other_school_gid, location_gid, "read")

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
            rbac.add_permission(board_gid, location_gid, "*")
            rbac.add_permission(location_gid, board_gid, "read")

            for other_school_gid in self.schools_for_board(board_gid):
                if other_school_gid == school_gid:
                    continue

                rbac.add_permission(other_school_gid, location_gid, "read")

                for other_location_gid in self.locations_for_school(other_school_gid):
                    rbac.add_permission(school_gid, other_location_gid, "read")

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
