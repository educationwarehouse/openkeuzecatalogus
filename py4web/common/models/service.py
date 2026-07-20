"""Service-context database helpers for the py4web app."""

from typedal import TypeDAL

from common.models.database_context import Py4webDatabaseContext
from shared_code.data_model import define_tables
from shared_code.modules.auth import AuthAdapter


def db_with_service_context(appname: str) -> TypeDAL:
    """Build a typed DAL with service-scoped (system) auth context."""
    db = Py4webDatabaseContext.with_injected(auth_adapter=AuthAdapter.for_service(appname))

    return define_tables(db)
