"""Backend dependency container for py4web runtime services."""

from endow import BackendBase

from common.models.database_context import Py4webDatabaseContext
from shared_code.modules.auth import AuthContext
from shared_code.modules.auth.module import AuthSupportBackend
from shared_code.modules.comparison import ComparisonBackend
from shared_code.modules.methods import MethodBackend
from shared_code.modules.organisations import OrganisationBackend
from shared_code.modules.products import ProductBackend
from shared_code.modules.search_relevance import SearchRelevance
from shared_code.modules.suppliers import SupplierBackend
from shared_code.modules.visions import VisionBackend
from shared_code.services import Applogger, EntreeOAuthService, ErrorTicketService, Mailer


class Py4webBackend(BackendBase):
    """Root DI graph for py4web runtime services."""

    db: Py4webDatabaseContext

    # services:
    auth_context: AuthContext
    applog: Applogger
    entree_oauth: EntreeOAuthService
    error_tickets: ErrorTicketService
    mailer: Mailer

    # domains:
    auth_support: AuthSupportBackend
    comparison: ComparisonBackend
    methods: MethodBackend
    organisations: OrganisationBackend
    products: ProductBackend
    suppliers: SupplierBackend
    visions: VisionBackend
    search_relevance: SearchRelevance
