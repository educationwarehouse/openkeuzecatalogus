"""Authorization rules for guided decision processes."""

from endow.policy import Allow, AuthorizationResult
from typedal import QueryBuilder

from shared_code.data_model import DecisionProcess, DecisionTeam, Identity, Organisation, OrganisationType
from shared_code.infra.database.policy import ReusablePolicy


class DecisionProcessPolicy(ReusablePolicy):
    """Check access through the existing organisation RBAC graph."""

    def team_query(self, privilege: str) -> QueryBuilder[DecisionTeam]:
        """Return teams reachable with one privilege, without selecting columns."""
        registered_team_gids = Identity.where(Identity.object_type == "group").select(Identity.object_id)
        location_gids = Organisation.where(Organisation.organisation_type == OrganisationType.LOCATION).select(
            Organisation.gid
        )
        teams = DecisionTeam.where(
            DecisionTeam.gid.belongs(registered_team_gids) & DecisionTeam.location_gid.belongs(location_gids)
        )
        if self.auth.is_service() or self.auth.is_admin():
            return teams

        # the same subquery text lands in the SQL twice, once per column
        permitted = self.auth.permitted_object_ids_subquery(privilege)
        if privilege != "read":
            return teams.where(DecisionTeam.gid.belongs(permitted))
        return teams.where((DecisionTeam.gid.belongs(permitted)) | (DecisionTeam.location_gid.belongs(permitted)))

    def _team_scope(self, privilege: str) -> QueryBuilder[DecisionTeam]:
        """Return a gid-only subselect over the reachable teams, for use inside `belongs()`."""
        return self.team_query(privilege).select(DecisionTeam.gid)

    def _request(self, privilege: str) -> AuthorizationResult[QueryBuilder[DecisionProcess]]:
        """Apply the actor's organisation-derived team scope to processes."""
        if self.auth.is_service() or self.auth.is_admin():
            return Allow(apply=lambda query: query)

        teams = self._team_scope(privilege)
        return Allow(apply=lambda query: query.where(lambda table: table.team_gid.belongs(teams)))

    def request_read(self) -> AuthorizationResult[QueryBuilder[DecisionProcess]]:
        """Return processes the actor may inspect."""
        return self._request("read")

    def request_update(self) -> AuthorizationResult[QueryBuilder[DecisionProcess]]:
        """Return processes the actor may change."""
        return self._request("write")

    def can_manage_location(self, location_gid: str) -> bool:
        """Return whether a team may be created below this location."""
        # one target, so a point lookup rather than a scope; `has_permission` honours "*" grants
        # the same way `get_permissions` does (edwh_auth_rbac/model.py:1013 vs :1064).
        return self.auth.is_admin() or self.auth.is_service() or self.auth.has_permission(location_gid, "write")

    def can_manage_team(self, team_gid: str) -> bool:
        """Return whether an actor may start or change the selected team's workflow."""
        return self.auth.is_admin() or self.auth.is_service() or self.auth.has_permission(team_gid, "write")
