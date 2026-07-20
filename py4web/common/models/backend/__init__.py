"""Backend wiring for the py4web app."""

from shared_code.data_model import define_tables
from shared_code.modules.auth import (
    AuthActor,
    AuthAdapter,
)

from .auth_cls import AppAuth
from .auth_translations import setup_validator_translations
from .backend_base import Py4webBackend
from .session import session

setup_validator_translations()


auth_adapter = AuthAdapter(
    # adapter that binds backend to py4web's auth + rbac
    get_actor=lambda: (
        AuthActor(
            kind="user",
            id=str(u.gid),
            email=u.email,
            name=u.full_name,
        )
        if (u := auth.get_user())
        else AuthActor(
            kind="anonymous",
            id=None,
            email=None,
            name=None,
        )
    ),
    get_roles=lambda _: set(),
    get_permissions=lambda _: set(),
    # todo: currently a duplication of the 'service' one - should possibly check 'subject' with actor.gid ?
    #       (although that would break during e.g. post-email-validation logic)
    grant_membership=lambda self, subject, role: self.raw_rbac.add_membership(subject, role),
    revoke_membership=lambda self, subject, role: self.raw_rbac.remove_membership(subject, role),
    check_membership=lambda self, role: self.raw_rbac.has_membership(self.id, role) if self.id else False,
    check_permission=lambda self, permission: False,  # todo
)

backend = Py4webBackend.with_injected(auth_adapter=auth_adapter)
db = backend.db
auth_context = backend.auth_context

define_tables(db)

auth = AppAuth.from_dependencies(session, db, backend)

__all__ = [
    "AppAuth",
    "auth",
    "auth_context",
    "backend",
    "session",
]
