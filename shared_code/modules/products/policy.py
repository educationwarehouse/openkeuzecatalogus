"""Product authorization policy."""

from endow.policy import AuthorizationResult
from typedal import QueryBuilder

from shared_code.data_model import Product
from shared_code.infra.database.policy import ReusablePolicy


class ProductPolicy(ReusablePolicy):
    """Authorization helpers for product-domain operations."""

    def request_read(self) -> AuthorizationResult[QueryBuilder[Product]]:
        """Return the read scope for product queries."""
        return self._request_read_from_supplier_memberships()
