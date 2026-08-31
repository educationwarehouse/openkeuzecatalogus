"""Method authorization policy."""

from endow.policy import AuthorizationResult
from typedal import QueryBuilder

from shared_code.data_model import Method
from shared_code.infra.database.policy import ReusablePolicy


class MethodPolicy(ReusablePolicy):
    """Authorization helpers for method-domain operations."""

    def request_read(self) -> AuthorizationResult[QueryBuilder[Method]]:
        """Return the read scope for method queries."""
        return self._request_read_from_supplier_memberships()
