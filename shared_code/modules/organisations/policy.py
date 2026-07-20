"""Organisation authorization policy."""

import typing

from endow.policy import AuthorizationResult
from typedal import QueryBuilder

from shared_code.infra.database.policy import ReusablePolicy
from shared_code.modules.auth.contract import AuthContext

if typing.TYPE_CHECKING:
    from shared_code.data_model import Organisation


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
