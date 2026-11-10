"""Authentication actor and context contracts."""

import dataclasses as dc
import typing as t
from uuid import UUID

import pydal
from edwh_auth_rbac import AuthRbac
from endow import Injectable

from shared_code.data_model.constants import ROLE_ADMIN
from shared_code.services.applog import Applogger

if t.TYPE_CHECKING:
    from shared_code.infra.database import DatabaseContext

ActorKind = t.Literal["user", "service", "anonymous"]
AuthScope = t.Literal["read", "write", "invite"]


# subquery or iterable:
type PermittedObjects = str | t.Collection[str]


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
        check_permission(self, gid, scope)

      These are optional constructor inputs. If omitted:
        has_membership(role) -> role in roles
        has_permission(gid, scope) -> False
    """

    get_actor: t.Callable[[], AuthActor]
    get_session_gid: t.Callable[[], str | None] = lambda: None
    get_roles: t.Callable[[AuthContext], set[str]] = lambda self: set()
    get_permissions: t.Callable[[AuthContext], set[str]] = lambda self: set()
    get_permitted_object_ids: t.Callable[[AuthContext, str], set[str]] = lambda self, privilege: set()
    get_permitted_object_ids_subquery: t.Callable[[AuthContext, str], PermittedObjects] = lambda self, privilege: (
        frozenset()
    )
    grant_membership: t.Callable[[AuthContext, str, str], t.Any] | None = None
    revoke_membership: t.Callable[[AuthContext, str, str], t.Any] | None = None
    check_membership: t.Callable[[AuthContext, str], bool] | None = None
    check_subject_membership: t.Callable[[AuthContext, str, str], bool] | None = None
    check_permission: t.Callable[[AuthContext, str, AuthScope], bool] | None = None

    @classmethod
    def for_service(cls, service_name: str) -> AuthAdapter:
        """Build an auth adapter for internal service callers."""
        actor = AuthActor(
            kind="service",
            id=f"service:{service_name}",
            email=f"{service_name}@internal",
            name=service_name,
        )

        return edwh_rbac_adapter(
            get_actor=lambda: actor,
            get_rbac=lambda ctx: ctx.raw_rbac,
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

        self._rbac = AuthRbac(t.cast(pydal.DAL, self.db))

        # Define the rbac model once per DAL: redefining replaces `db.identity` & co., leaving typed models such as
        # `Identity` bound to the old Table objects; mixing both in one query then fails with "Name conflict".
        if not getattr(self.db, "_rbac_model_defined", False):
            self._rbac.define_model(
                allowed_types=["user", "group", "item"],
                redefine=True,
                migrate=False,
            )
            self.db._rbac_model_defined = True
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

    @property
    def session_gid(self) -> str | None:
        """Return the current session gid when available."""
        return self.adapter.get_session_gid()

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

    def has_subject_membership(self, subject: str | UUID, role: str | UUID) -> bool:
        """Return whether one subject belongs to the given role."""
        if not self.adapter.check_subject_membership:
            raise NotImplementedError("AuthContext does not provide arbitrary membership checks")

        return self.adapter.check_subject_membership(self, str(subject), str(role))

    def has_permission(self, gid: str, scope: AuthScope) -> bool:
        """Return whether the actor has `scope` on the object identified by `gid`."""
        if self.adapter.check_permission:
            return self.adapter.check_permission(self, gid, scope)

        return False

    def permitted_object_ids(self, privilege: str) -> set[str]:
        """Return object identities the actor may access with one privilege."""
        # note: not your first choice since it preloads, prefer `permitted_object_ids_subquery`,
        #       only use this as a last resort.
        return self.adapter.get_permitted_object_ids(self, privilege)

    def permitted_object_ids_subquery(self, privilege: str) -> PermittedObjects:
        """Return a subquery over the object identities the actor may access with one privilege.

        Prefer this over `permitted_object_ids`: it composes into the surrounding query
        instead of preloading every gid.

        The result is raw SQL, so hand it to `belongs()` and nothing else: never iterate,
        index or `len()` it. An actor without an identity yields an empty collection, which
        pydal renders as `(1=0)`.
        """
        return self.adapter.get_permitted_object_ids_subquery(self, privilege)

    def is_admin(self) -> bool:
        """Return whether the actor has the admin role."""
        return self.has_membership(ROLE_ADMIN)

    @classmethod
    def for_service(cls, service_name: str) -> t.Self:
        """Build a service-scoped context for internal callers."""
        return cls.with_injected(auth_adapter=AuthAdapter.for_service(service_name))


def _rbac_role_names(rbac: AuthRbac, actor_id: str | None) -> set[str]:
    """Return the role keys (group emails) the actor belongs to, including nested groups."""
    if not actor_id:
        return set()

    user = rbac.get_user(actor_id, return_memberships=True)
    if not user:
        return set()

    return {membership["email"] for membership in user.get("memberships", []) if membership["email"]}


def edwh_rbac_adapter(
    *,
    get_actor: t.Callable[[], AuthActor],
    get_rbac: t.Callable[[AuthContext], AuthRbac],
    get_session_gid: t.Callable[[], str | None] = lambda: None,
) -> AuthAdapter:
    """Build an adapter backed by an edwh-rbac instance."""
    return AuthAdapter(
        get_actor=get_actor,
        get_session_gid=get_session_gid,
        get_roles=lambda context: _rbac_role_names(get_rbac(context), context.id),
        get_permitted_object_ids=lambda context, privilege: (
            set(get_rbac(context).get_permissions(context.id, privilege)) if context.id else set()
        ),
        get_permitted_object_ids_subquery=lambda context, privilege: (
            # `get_permissions_subquery` returns SQL text, not a Query, whatever its docstring says.
            (get_rbac(context).get_permissions_subquery(context.id, privilege)) if context.id else frozenset()
        ),
        grant_membership=lambda context, subject, role: get_rbac(context).add_membership(subject, role),
        revoke_membership=lambda context, subject, role: get_rbac(context).remove_membership(subject, role),
        check_membership=lambda context, role: bool(context.id and get_rbac(context).has_membership(context.id, role)),
        check_subject_membership=lambda context, subject, role: bool(get_rbac(context).has_membership(subject, role)),
        check_permission=lambda context, gid, scope: bool(
            context.id and get_rbac(context).has_permission(context.id, gid, scope),
        ),
    )


__all__ = [
    "AuthActor",
    "AuthAdapter",
    "AuthContext",
    "AuthScope",
    "PermittedObjects",
    "edwh_rbac_adapter",
]
