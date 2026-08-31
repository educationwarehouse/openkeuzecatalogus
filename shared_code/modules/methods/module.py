"""Method domain module."""

import typing as t

from endow import Domain
from typedal import PaginatedRows, QueryBuilder

from shared_code.data_model import Method, Product, Supplier
from shared_code.infra.database.policy import TypeDALPolicyMixin
from shared_code.modules.auth.contract import AuthContext
from shared_code.modules.catalog_filters import CatalogFilters, ResolvedCatalogFilters
from shared_code.modules.catalog_filters.types import CatalogSortOption
from shared_code.modules.methods.policy import MethodPolicy
from shared_code.services import Applogger

if t.TYPE_CHECKING:
    from shared_code.infra.database import DatabaseContext


class MethodBackend(Domain, TypeDALPolicyMixin[Method]):
    """Method business flows and RBAC orchestration."""

    db: DatabaseContext
    auth: AuthContext
    policy: MethodPolicy
    filters: CatalogFilters
    applog: Applogger

    def _public_method_base_query(self) -> QueryBuilder[Method]:
        """Return the base public method query before request filters."""
        return Method.where(Method.available != "verwijderd").select(
            Method.ALL,
        )

    def resolve_public_method_filters(self, params: dict[str, t.Any] | None = None) -> ResolvedCatalogFilters:
        """Resolve request params into method filter state."""
        return self.filters.resolve(
            entity_kind="method",
            params=params or {},
            option_builder=self._public_method_base_query(),
            sort_options=self.public_sort_options(),
        )

    def list_my_methods(self) -> QueryBuilder[Method]:
        """Return methods visible to the current actor."""
        return self.request_read()

    def public_sort_options(self) -> dict[str, CatalogSortOption[Method]]:
        """Return public method sort options."""
        return self.filters.sort_options("method")

    def default_public_sort_option(self) -> CatalogSortOption[Method]:
        """Return the configured default method sort option."""
        return self.filters.default_sort_option("method")

    def public_sort_option(self, sort: str) -> CatalogSortOption[Method]:
        """Return the requested sort option, falling back to the configured default."""
        return self.filters.sort_option("method", sort)

    def list_public_methods(
        self,
        filters: ResolvedCatalogFilters | None = None,
        *,
        sort: str,
        page: int,
        limit: int,
    ) -> PaginatedRows[Method]:
        """Return public methods, selecting only public fields."""
        builder = self._public_method_base_query()
        builder = self.filters.apply(builder, filters)
        builder = builder.join("supplier", method="inner").select(Supplier.gid, Supplier.name)
        builder = builder.join("products", method="inner").select(Product.gid)
        # inner because a method without products is useless

        builder = Method.apply_orderby(self.public_sort_option(sort).order, builder)

        rows = builder.paginate(page=page, limit=limit)
        self.applog.log_catalog_search(entity_kind="method", filters=filters, rows=rows)
        return rows
