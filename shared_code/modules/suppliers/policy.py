"""Supplier authorization policy."""

import typing

from endow.policy import AuthorizationResult
from typedal import QueryBuilder

from shared_code.data_model.constants import ROLE_ADMIN
from shared_code.infra.database.policy import ReusablePolicy

if typing.TYPE_CHECKING:
    from shared_code.data_model.tables.supplier import Supplier


class SupplierPolicy(ReusablePolicy):
    """Authorization helpers for supplier-domain operations."""

    def can_access_supplier(self, supplier_gid: str) -> bool:
        """Return whether the current actor may access one supplier."""
        return self.auth.has_membership(ROLE_ADMIN) or self.auth.has_membership(supplier_gid)

    def request_read(self) -> AuthorizationResult[QueryBuilder[Supplier]]:
        """Return the read scope for supplier queries."""
        return self._request_read_from_recursive_memberships("supplier_model")
