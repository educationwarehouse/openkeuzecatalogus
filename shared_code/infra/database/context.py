"""Project-specific database context types."""

import os
import typing as t

from endow import Injectable
from typedal import TypeDAL

from shared_code.modules.auth import AuthContext
from shared_code.services.applog import Applogger


class DatabaseContext(TypeDAL, Injectable):
    """Generic runtime database with attached project services."""

    auth: AuthContext
    applog: Applogger

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
