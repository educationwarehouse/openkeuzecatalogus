"""Backend dependency container for py4web runtime services."""

from endow import BackendBase

from common.models.database_context import Py4webDatabaseContext
from shared_code.modules.auth import AuthContext
from shared_code.modules.auth.module import AuthSupportBackend
from shared_code.modules.methods import MethodBackend
from shared_code.modules.organisations import OrganisationBackend
from shared_code.modules.products import ProductBackend
from shared_code.modules.suppliers import SupplierBackend
from shared_code.services import Applogger, EntreeOAuthService, Mailer


class Py4webBackend(BackendBase):
    """Root DI graph for py4web runtime services."""

    db: Py4webDatabaseContext

    # services:
    mailer: Mailer
    applog: Applogger
    entree_oauth: EntreeOAuthService
    auth_context: AuthContext

    # domains:
    auth_support: AuthSupportBackend
    methods: MethodBackend
    organisations: OrganisationBackend
    products: ProductBackend
    suppliers: SupplierBackend
