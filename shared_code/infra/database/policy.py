"""Shared policy helpers for database-backed modules."""

import abc
import typing as t

from endow.policy import Allow, AuthorizationResult, BasePolicy, Deny
from typedal import QueryBuilder, TypedTable
from typedal.helpers import classproperty

if t.TYPE_CHECKING:
    from shared_code.data_model.tables import BaseTable
    from shared_code.infra.database import DatabaseContext
    from shared_code.modules.auth import AuthContext


class ReusablePolicy(BasePolicy, abc.ABC):
    """Reusable authorization policy contract."""

    auth: AuthContext
    db: DatabaseContext

    @abc.abstractmethod
    def request_read(self) -> AuthorizationResult:
        """Return the authorization result for a read request."""
        ...

    def request_update(self) -> AuthorizationResult:
        """Return the authorization result for an update request."""
        return Deny("Write access is not available for this resource.")

    def _membership_object_ids_for_table(self, table_name: str) -> list[str]:
        """Return recursive membership object ids for the current actor and table."""
        if self.auth.is_service() or self.auth.is_admin():
            return []

        user = self.auth.id
        assert user, "Read requests require a user or service actor identifier"

        membership_rows = self.db.executesql(
            f"""
            select distinct(object_id)
                from recursive_memberships
                         INNER JOIN {table_name} on object_id = {table_name}.gid
                where root = %(user)s -- user gid
            """,  # noqa S608: `table_name` is in our control so no SQL injection possible
            placeholders={"user": user},
        )

        return [row[0] for row in membership_rows]

    def _request_read_from_recursive_memberships[T: BaseTable](
        self,
        table_name: str,
    ) -> AuthorizationResult[QueryBuilder[T]]:
        """Build a read scope from recursive RBAC memberships for a model table."""
        if self.auth.is_service() or self.auth.is_admin():
            return Allow(apply=lambda query: query)

        memberships = self._membership_object_ids_for_table(table_name)
        return Allow(
            apply=lambda qb: qb.where(lambda table: table.gid.belongs(memberships)),
        )

    def _request_read_from_supplier_memberships[T: BaseTable](
        self,
        supplier_gid_field: str = "supplier_gid",
    ) -> AuthorizationResult[QueryBuilder[T]]:
        """Build a read scope from recursive supplier memberships."""
        if self.auth.is_service() or self.auth.is_admin():
            return Allow(apply=lambda query: query)

        memberships = self._membership_object_ids_for_table("supplier_model")
        return Allow(
            apply=lambda qb: qb.where(
                lambda table: table[supplier_gid_field].belongs(memberships),
            ),
        )

    def _request_update_from_permissions[T: BaseTable](self) -> AuthorizationResult[QueryBuilder[T]]:
        """Build an update scope from the current actor's inherited RBAC permissions."""
        if self.auth.is_service() or self.auth.is_admin():
            return Allow(apply=lambda query: query)

        permitted_gids = self.auth.permitted_object_ids("write")
        return Allow(apply=lambda query: query.where(lambda table: table.gid.belongs(permitted_gids)))

    def require_read(self) -> Allow:
        """Require read access and return the enforced authorization result."""
        return self.request_read().require()

    def require_update(self) -> Allow:
        """Require update access and return the enforced authorization result."""
        return self.request_update().require()


class TypeDALPolicyMixin[T: TypedTable]:
    """Mixin that binds a policy object to a typed DAL model."""

    policy: ReusablePolicy

    @classproperty
    def model(cls) -> type[T]:
        """Return the concrete typed DAL model for this mixin."""
        return next(
            args[0]
            for _ in getattr(cls, "__orig_bases__", ())
            if t.get_origin(_) is TypeDALPolicyMixin and (args := t.get_args(_))
        )

    def request_read(self) -> QueryBuilder[T]:
        """Request read access for the bound model."""
        authz: Allow[QueryBuilder[T]] = self.policy.require_read()

        builder = self.model.permissions(read=True, insert=False, update=False, delete=False)

        return authz(builder)

    def request_update(self) -> QueryBuilder[T]:
        """Request update access for the bound model."""
        authz: Allow[QueryBuilder[T]] = self.policy.require_update()

        builder = self.model.permissions(read=True, insert=False, update=True, delete=False)

        return authz(builder)

    # todo: add request_create() and request_delete() policy contracts
