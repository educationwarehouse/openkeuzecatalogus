"""Backend wiring for the py4web app."""

from shared_code.data_model import define_tables
from shared_code.modules.auth import (
    AuthActor,
    edwh_rbac_adapter,
)

from .auth_cls import AppAuth
from .auth_translations import setup_validator_translations
from .backend_base import Py4webBackend
from .session import session

setup_validator_translations()


auth_adapter = edwh_rbac_adapter(
    # adapter that binds backend to py4web's auth + rbac
    get_actor=lambda: (
        AuthActor(
            kind="user",
            id=u.gid,
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
    get_session_gid=lambda: session.get("uuid"),
    get_rbac=lambda ctx: ctx.raw_rbac,
)

backend = Py4webBackend.with_injected(auth_adapter=auth_adapter)
db = backend.db
auth_context = backend.auth_context

define_tables(db, caching=backend.caching)

auth = AppAuth.from_dependencies(session, db, backend)

__all__ = [
    "AppAuth",
    "auth",
    "auth_context",
    "backend",
    "db",
    "session",
]
