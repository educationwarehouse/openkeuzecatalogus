"""Py4web-specific database context type."""

import typing as t

from typedal.for_py4web import DAL

from common import settings
from shared_code.infra.database.context import DatabaseContext


class Py4webDatabaseContext(DAL, DatabaseContext):
    """Py4web DAL fixture with attached project services."""

    @classmethod
    def from_env(cls) -> t.Self:
        """Build a database context from the py4web environment."""
        return cls(
            settings.DB_URI,
            folder=settings.DB_FOLDER,
            pool_size=settings.DB_POOL_SIZE,
            migrate=settings.DB_MIGRATE,
            fake_migrate=settings.DB_FAKE_MIGRATE,
        )
