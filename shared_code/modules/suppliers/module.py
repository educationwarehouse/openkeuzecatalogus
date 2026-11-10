"""Supplier domain module."""

import typing as t

from endow import Domain
from typedal import PaginatedRows, QueryBuilder

from shared_code.data_model import update_effectivedated
from shared_code.data_model.constants import Predicate
from shared_code.data_model.tables import (
    AuthUser,
    Method,
    MethodEd,
    Product,
    ProductEd,
    Supplier,
    SupplierEd,
    Tagged,
    TaggedEd,
    Vision,
    VisionEd,
)
from shared_code.infra.database.policy import TypeDALPolicyMixin
from shared_code.modules.auth import AuthContext
from shared_code.modules.suppliers.policy import SupplierPolicy
from shared_code.util.email import extract_email_domain

if t.TYPE_CHECKING:
    from shared_code.infra.database import DatabaseContext


class SupplierBackend(Domain, TypeDALPolicyMixin[Supplier]):
    """Supplier business flows and RBAC orchestration."""

    db: DatabaseContext
    auth: AuthContext
    policy: SupplierPolicy

    def _archive_actor(self) -> str:
        if not (self.auth.is_service() or self.auth.is_admin()):
            raise PermissionError("Alleen beheerders mogen leveranciers verwijderen.")
        actor = self.auth.get_email() or self.auth.id
        assert actor, "An admin or service actor must have an identifier"
        return actor

    def _archive_visions(self, olid: str | None, actor: str) -> None:
        if not olid:
            return
        for vision_gid in Vision.where(olid=olid).column(Vision.gid):
            update_effectivedated(self.db, VisionEd, VisionEd.gid == vision_gid, last_saved_by=actor, delete=True)

    def _archive_product(self, product_gid: str, actor: str) -> None:
        product = Product.where(gid=product_gid).first()
        if not product:
            raise ValueError("Product niet gevonden.")
        for relation_gid in Tagged.where(
            (Tagged.predicate == Predicate.BUNDLES)
            & ((Tagged.subject_gid == product_gid) | (Tagged.object_gid == product_gid))
        ).column(Tagged.gid):
            update_effectivedated(self.db, TaggedEd, TaggedEd.gid == relation_gid, last_saved_by=actor, delete=True)
        self._archive_visions(product.olid, actor)
        update_effectivedated(self.db, ProductEd, ProductEd.gid == product_gid, last_saved_by=actor, delete=True)

    def archive_product(self, product_gid: str) -> None:
        """Archive a product and its bundle and vision connections."""
        actor = self._archive_actor()
        self._archive_product(product_gid, actor)
        self.db.commit()

    def _archive_method(self, method_gid: str, actor: str) -> None:
        method = Method.where(gid=method_gid).first()
        if not method:
            raise ValueError("Methode niet gevonden.")
        for product_gid in Product.where(method_gid=method_gid).column(Product.gid):
            self._archive_product(product_gid, actor)
        self._archive_visions(method.olid, actor)
        update_effectivedated(self.db, MethodEd, MethodEd.gid == method_gid, last_saved_by=actor, delete=True)

    def archive_method(self, method_gid: str) -> None:
        """Archive a method and its current products."""
        actor = self._archive_actor()
        self._archive_method(method_gid, actor)
        self.db.commit()

    def archive_supplier(self, supplier_gid: str) -> None:
        """Archive a supplier and its current methods and products."""
        actor = self._archive_actor()
        supplier = Supplier.where(gid=supplier_gid).first()
        if not supplier:
            raise ValueError("Leverancier niet gevonden.")

        for method_gid in Method.where(supplier_gid=supplier_gid).column(Method.gid):
            self._archive_method(method_gid, actor)
        for product_gid in Product.where(supplier_gid=supplier_gid).column(Product.gid):
            self._archive_product(product_gid, actor)
        self._archive_visions(supplier.olid, actor)
        update_effectivedated(self.db, SupplierEd, SupplierEd.gid == supplier_gid, last_saved_by=actor, delete=True)
        self.db.commit()

    def grant_memberships(self, user: AuthUser) -> None:
        """Grant the matching supplier membership for a user email, if any."""
        if not user.gid:
            return None

        supplier = self._find_supplier_by_email_domain(user.email)
        if not supplier:
            return None

        self.auth.add_membership(user.gid, supplier.gid)
        return None

    @classmethod
    def _find_supplier_by_email_domain(cls, email: str | None) -> Supplier | None:
        """Return the supplier matching the normalized email domain, if any."""
        if not (domain := extract_email_domain(email)):
            return None

        return Supplier.where(Supplier.email_domains.contains(domain)).first()

    def list_my_suppliers(self) -> QueryBuilder[Supplier]:
        """Return suppliers visible to the current actor."""
        return self.request_read()

    def get_my_supplier(self, supplier_gid: str) -> Supplier | None:
        """Return one supplier after applying the actor's access policy."""
        builder = self.request_update()
        return builder.where(gid=supplier_gid).first()

    def list_public_suppliers(self) -> PaginatedRows[Supplier]:
        """Return (active) subppliers, selecting only public fields."""
        return Supplier.select(
            Supplier.name,
            Supplier.olid,
            Supplier.logo_url,
            Supplier.status_visions,
        ).paginate(limit=0, page=1)
