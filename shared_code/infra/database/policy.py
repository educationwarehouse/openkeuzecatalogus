"""Shared policy helpers for database-backed modules."""

import abc
import typing as t

from endow.policy import Allow, AuthorizationResult, BasePolicy
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

    def _request_read_from_recursive_memberships[T: BaseTable](
        self,
        table_name: str,
    ) -> AuthorizationResult[QueryBuilder[T]]:
        """Build a read scope from recursive RBAC memberships for a model table."""
        if self.auth.is_service() or self.auth.is_admin():
            return Allow(apply=lambda query: query)

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

        memberships = [row[0] for row in membership_rows]

        return Allow(
            apply=lambda qb: qb.where(lambda table: table.gid.belongs(memberships)),
        )

    def require_read(self) -> Allow:
        """Require read access and return the enforced authorization result."""
        return self.request_read().require()

    # todo: same for
    # request_update()
    # request_delete()
    # request_create()


class TypeDALPolicyMixin[T: TypedTable]:
    """Mixin that binds a policy object to a typed DAL model."""

    policy: ReusablePolicy

    # todo: finish
    # request_read() -> AuthorizedRead[T]
    # request_update() -> AuthorizedUpdate[TEdit]
    # request_delete() -> AuthorizedDelete[T]
    # request_create() -> AuthorizedCreate[TCreate]

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
