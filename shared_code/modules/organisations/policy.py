"""Organisation authorization policy."""

from endow.policy import AuthorizationResult
from typedal import QueryBuilder

from shared_code.data_model import Organisation, OrganisationType
from shared_code.infra.database.policy import ReusablePolicy
from shared_code.modules.auth import AuthContext


class OrganisationPolicy(ReusablePolicy):
    """Authorization helpers for organisation relation mutations."""

    auth: AuthContext

    def can_manage_relations(self) -> bool:
        """Return whether the current actor may manage organisation relations."""
        return self.auth.is_service() or self.auth.is_admin()

    def require_manage_relations(self) -> None:
        """Require organisation relation management access."""
        if not self.can_manage_relations():
            raise PermissionError("Only admins or services may manage organisation relations.")

    def request_read(self) -> AuthorizationResult[QueryBuilder[Organisation]]:
        """Return the read scope for organisation queries."""
        return self._request_read_from_recursive_memberships("organisation_model")

    def organisation_query(
        self,
        organisation_type: OrganisationType,
        privilege: str = "read",
    ) -> QueryBuilder[Organisation]:
        """Return organisations of one type the actor holds `privilege` on.

        Deliberately a second scope beside `request_read`, narrower in a different direction:
        this one filters on RBAC *permission grants* while `request_read` filters on *recursive
        memberships*. They are not interchangeable, so neither delegates to the other.
        Reconciling them is still open.
        """
        builder = Organisation.where(Organisation.organisation_type == organisation_type)
        if self.auth.is_admin() or self.auth.is_service():
            return builder

        permitted = self.auth.permitted_object_ids_subquery(privilege)
        return builder.where(Organisation.gid.belongs(permitted))
