"""Authentication actor and context contracts."""

import dataclasses as dc
import typing as t
from uuid import UUID

from edwh_auth_rbac import AuthRbac
from endow import Injectable

from shared_code.data_model.constants import ROLE_ADMIN
from shared_code.services.applog import Applogger

if t.TYPE_CHECKING:
    from shared_code.infra.database import DatabaseContext

ActorKind = t.Literal["user", "service", "anonymous"]


@dc.dataclass(frozen=True)
class AuthActor:
    """Identity information for an authenticated or anonymous actor."""

    kind: ActorKind
    id: str | None
    email: str | None = None
    name: str | None = None


@dc.dataclass(frozen=True)
class AuthAdapter:
    """Low-level auth providers and mutation hooks used by AuthContext.

    Naming convention:

    - Public values are exposed as properties:
        actor
        user
        roles
        permissions

    - Input value providers use get_*:
        get_actor()
        get_roles(self)
        get_permissions(self)

      These are constructor inputs. Providers return data, not booleans.
      Context-aware providers receive the current AuthContext as their first argument.

    - Public boolean checks use has_* / is_*:
        has_membership(...)
        has_permission(...)
        is_user()
        is_service()
        is_anonymous()

      These are the methods normal callers should use.

    - Input predicate overrides use check_*:
        check_membership(self, role)
        check_permission(self, permission)

      These are optional constructor inputs. If omitted:
        has_membership(role) -> role in roles
        has_permission(permission) -> permission in permissions
    """

    get_actor: t.Callable[[], AuthActor]
    get_roles: t.Callable[[AuthContext], set[str]] = lambda self: set()
    get_permissions: t.Callable[[AuthContext], set[str]] = lambda self: set()
    grant_membership: t.Callable[[AuthContext, str, str], t.Any] | None = None
    revoke_membership: t.Callable[[AuthContext, str, str], t.Any] | None = None
    check_membership: t.Callable[[AuthContext, str], bool] | None = None
    check_permission: t.Callable[[AuthContext, str], bool] | None = None

    @classmethod
    def for_service(cls, service_name: str) -> t.Self:
        """Build an auth adapter for internal service callers."""
        actor = AuthActor(
            kind="service",
            id=f"service:{service_name}",
            email=f"{service_name}@internal",
            name=service_name,
        )

        return cls(
            get_actor=lambda: actor,
            get_roles=lambda self: set(),
            get_permissions=lambda self: set(),
            grant_membership=lambda self, subject, role: self.raw_rbac.add_membership(subject, role),
            revoke_membership=lambda self, subject, role: self.raw_rbac.remove_membership(subject, role),
            check_membership=lambda self, role: self.raw_rbac.has_membership(self.id, role) if self.id else False,
        )


class AuthContext(Injectable):
    """Framework-agnostic authentication context."""

    auth_adapter: AuthAdapter
    db: DatabaseContext
    applog: Applogger

    _rbac: AuthRbac | None = None

    @property
    def raw_rbac(self) -> AuthRbac:
        """Return the underlying `edwh-rbac` instance for identity and group maintenance.

        This bypasses the higher-level auth adapter so internal code can call RBAC
        APIs that are not exposed by `AuthContext`, such as `add_user`,
        `add_group`, and `update_identity`.
        """
        if self._rbac:
            return self._rbac

        self._rbac = AuthRbac(self.db)
        self._rbac.define_model(
            allowed_types=["user", "group", "item"],
            redefine=True,
            migrate=False,
        )
        self.db.commit()
        return self._rbac

    @property
    def adapter(self) -> AuthAdapter:
        """Return the configured auth adapter."""
        return self.auth_adapter

    @property
    def actor(self) -> AuthActor:
        """Return the current actor."""
        return self.adapter.get_actor()

    def is_user(self) -> bool:
        """Return whether the actor represents a user."""
        return self.actor.kind == "user"

    def is_anonymous(self) -> bool:
        """Return whether the actor is anonymous."""
        return self.actor.kind == "anonymous"

    def is_service(self) -> bool:
        """Return whether the actor represents an internal service."""
        return self.actor.kind == "service"

    @property
    def user(self) -> AuthActor | None:
        """Return the actor when it represents a user."""
        actor = self.actor
        return actor if actor.kind == "user" else None

    @property
    def roles(self) -> list[str]:
        """Return the current role names."""
        return list(self.adapter.get_roles(self))

    @property
    def permissions(self) -> list[str]:
        """Return the current permission names."""
        return list(self.adapter.get_permissions(self))

    @property
    def id(self) -> str | None:
        """Return the actor identifier."""
        return self.actor.id

    def get_email(self) -> str | None:
        """Return the actor email address when available."""
        return self.actor.email

    def add_membership(self, subject: str | UUID, role: str | UUID) -> None:
        """Grant a membership through the configured auth adapter."""
        if not self.adapter.grant_membership:
            raise NotImplementedError("AuthContext does not provide membership mutation")

        subject = str(subject)
        role = str(role)

        self.adapter.grant_membership(self, subject, role)
        self.applog.try_fire(
            {
                "kind": "event",
                "action": "grant-membership",
                "user_gid": self.id,
                "related": subject,
                "details": {
                    "subject_gid": subject,
                    "role_gid": role,
                    "actor_gid": self.id,
                    "actor_email": self.get_email(),
                    "actor_kind": self.actor.kind,
                },
            },
        )

    def remove_membership(self, subject: str | UUID, role: str | UUID) -> None:
        """Revoke a membership through the configured auth adapter."""
        if not self.adapter.revoke_membership:
            raise NotImplementedError("AuthContext does not provide membership mutation")

        subject = str(subject)
        role = str(role)
        self.adapter.revoke_membership(self, subject, role)
        self.applog.try_fire(
            {
                "kind": "event",
                "action": "revoke-membership",
                "user_gid": self.id,
                "related": subject,
                "details": {
                    "subject_gid": subject,
                    "role_gid": role,
                    "actor_gid": self.id,
                    "actor_email": self.get_email(),
                    "actor_kind": self.actor.kind,
                },
            },
        )

    def has_membership(self, role: str) -> bool:
        """Return whether the actor belongs to the given role."""
        if self.adapter.check_membership:
            return self.adapter.check_membership(self, role)

        return role in self.roles

    def has_permission(self, permission: str) -> bool:
        """Return whether the actor has the given permission."""
        if self.adapter.check_permission:
            return self.adapter.check_permission(self, permission)

        return permission in self.permissions

    def is_admin(self) -> bool:
        """Return whether the actor has the admin role."""
        return self.has_membership(ROLE_ADMIN)

    @classmethod
    def for_service(cls, service_name: str) -> t.Self:
        """Build a service-scoped context for internal callers."""
        return cls.with_injected(auth_adapter=AuthAdapter.for_service(service_name))


__all__ = [
    "AuthActor",
    "AuthAdapter",
    "AuthContext",
]
