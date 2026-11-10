"""Project-specific database context types."""

import os
import typing as t

from endow import Injectable
from typedal import TypeDAL

if t.TYPE_CHECKING:
    from shared_code.modules.auth import AuthContext
    from shared_code.services.applog import Applogger
    from shared_code.services.caching import CacheService


class DatabaseContext(TypeDAL, Injectable):
    """Generic runtime database with attached project services."""

    auth: AuthContext
    applog: Applogger
    caching: CacheService

    # set by `AuthContext.raw_rbac` once edwh-rbac's tables are defined on this DAL (unannotated: not injected)
    _rbac_model_defined = False

    @classmethod
    def from_env(cls) -> t.Self:
        """Build a database context from environment variables."""
        return cls(
            os.environ["POSTGRES_URI"],
            # folder=DB_FOLDER,
            # pool_size=DB_POOL_SIZE,
            # migrate=DB_MIGRATE,
            # fake_migrate=DB_FAKE_MIGRATE,
        )

    def close(self) -> None:
        """Close the database and release hook/dialect references."""
        # platform-specific:
        auth_context = getattr(self, "auth", None)
        raw_rbac = getattr(auth_context, "_rbac", None)

        if auth_context and raw_rbac:
            raw_rbac.db = None
            auth_context._rbac = None

        super().close()
