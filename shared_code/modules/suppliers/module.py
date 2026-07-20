"""Supplier domain module."""

import typing as t

from endow import Domain
from typedal import QueryBuilder

from shared_code.data_model.tables import AuthUser, Supplier
from shared_code.infra.database.policy import TypeDALPolicyMixin
from shared_code.modules.auth.contract import AuthContext
from shared_code.modules.suppliers.policy import SupplierPolicy
from shared_code.util.email import extract_email_domain

if t.TYPE_CHECKING:
    from shared_code.infra.database import DatabaseContext


class SupplierBackend(Domain, TypeDALPolicyMixin[Supplier]):
    """Supplier business flows and RBAC orchestration."""

    db: DatabaseContext
    auth: AuthContext
    policy: SupplierPolicy

    def grant_memberships(self, user: AuthUser) -> None:
        """Grant the matching supplier membership for a user email, if any."""
        if not user.gid:
            return None

        supplier = self._find_supplier_by_email_domain(user.email)
        if not supplier:
            return None

        self.auth.add_membership(str(user.gid), str(supplier.gid))
        return None

    @classmethod
    def _find_supplier_by_email_domain(cls, email: str | None) -> Supplier | None:
        """Return the supplier matching the normalized email domain, if any."""
        if not (domain := extract_email_domain(email)):
            return None

        return Supplier.where(Supplier.email_domains.contains(domain)).first()

    def list_suppliers(self) -> QueryBuilder[Supplier]:
        """Return suppliers visible to the current actor."""
        return self.request_read()
