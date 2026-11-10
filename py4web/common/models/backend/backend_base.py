"""Backend dependency container for py4web runtime services."""

from endow import BackendBase

from common.models.database_context import Py4webDatabaseContext
from shared_code.modules.auth import AuthContext
from shared_code.modules.auth.module import AuthSupportBackend
from shared_code.modules.catalogus_settings import CatalogusSettings
from shared_code.modules.comparison import ComparisonBackend
from shared_code.modules.decision_processes import DecisionProcessBackend
from shared_code.modules.favorites import FavoritesBackend
from shared_code.modules.methods import MethodBackend
from shared_code.modules.organisations import OrganisationBackend
from shared_code.modules.products import ProductBackend
from shared_code.modules.recommendations.similar_materials import SimilarMaterials
from shared_code.modules.search_relevance import SearchRelevance
from shared_code.modules.suppliers import SupplierBackend
from shared_code.modules.visions import VisionBackend
from shared_code.services import (
    Applogger,
    CacheService,
    DeferredWork,
    EntreeOAuthService,
    ErrorTicketService,
    LLMService,
    Mailer,
)

from .route_stats import ApplogRouteStats


class Py4webBackend(BackendBase):
    """Root DI graph for py4web runtime services."""

    db: Py4webDatabaseContext

    # services:
    auth_context: AuthContext
    applog: Applogger
    deferred: DeferredWork
    entree_oauth: EntreeOAuthService
    error_tickets: ErrorTicketService
    llm: LLMService
    mailer: Mailer
    route_stats: ApplogRouteStats
    caching: CacheService

    # domains:
    auth_support: AuthSupportBackend
    catalogus_settings: CatalogusSettings
    comparison: ComparisonBackend
    # shared rather than private-only: the admin app manages teams and processes too
    decision_processes: DecisionProcessBackend
    favorites: FavoritesBackend
    methods: MethodBackend
    organisations: OrganisationBackend
    products: ProductBackend
    suppliers: SupplierBackend
    visions: VisionBackend
    search_relevance: SearchRelevance
    similar_materials: SimilarMaterials
