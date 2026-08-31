"""Product domain module."""

import typing as t

from endow import Domain
from typedal import PaginatedRows, QueryBuilder

from shared_code.data_model import AnyDict, Method, Product, Supplier
from shared_code.infra.database.policy import TypeDALPolicyMixin
from shared_code.modules.auth.contract import AuthContext
from shared_code.modules.catalog_filters import CatalogFilters, ResolvedCatalogFilters
from shared_code.modules.catalog_filters.types import CatalogSortOption
from shared_code.modules.products.policy import ProductPolicy
from shared_code.services import Applogger

if t.TYPE_CHECKING:
    from shared_code.infra.database import DatabaseContext


class ProductBackend(Domain, TypeDALPolicyMixin[Product]):
    """Product business flows and RBAC orchestration."""

    db: DatabaseContext
    auth: AuthContext
    policy: ProductPolicy
    filters: CatalogFilters
    applog: Applogger

    def _public_product_base_query(self) -> QueryBuilder[Product]:
        """Return the base public product query before request filters."""
        return Product.where(Product.available != "verwijderd").select(Product.ALL)

    def resolve_public_product_filters(self, params: AnyDict | None = None) -> ResolvedCatalogFilters:
        """Resolve request params into product filter state."""
        return self.filters.resolve(
            entity_kind="product",
            params=params or {},
            option_builder=self._public_product_base_query(),
            sort_options=self.public_sort_options(),
        )

    def list_my_products(self) -> QueryBuilder[Product]:
        """Return products visible to the current actor."""
        return self.request_read()

    def public_sort_options(self) -> dict[str, CatalogSortOption[Product]]:
        """Return public product sort options."""
        return self.filters.sort_options("product")

    def default_public_sort_option(self) -> CatalogSortOption[Product]:
        """Return the configured default product sort option."""
        return self.filters.default_sort_option("product")

    def public_sort_option(self, sort: str) -> CatalogSortOption[Product]:
        """Return the requested sort option, falling back to the configured default."""
        return self.filters.sort_option("product", sort)

    def list_public_products(
        self,
        filters: ResolvedCatalogFilters | None = None,
        *,
        sort: str,
        page: int,
        limit: int,
    ) -> PaginatedRows[Product]:
        """Return public products, selecting only public fields."""
        builder = self._public_product_base_query()
        builder = self.filters.apply(builder, filters)

        builder = Product.apply_orderby(self.public_sort_option(sort).order, builder)
        builder = builder.join("method", method="inner").select(Method.gid, Method.name)
        builder = builder.join("supplier", method="inner").select(Supplier.gid, Supplier.name)

        rows = builder.paginate(page=page, limit=limit)
        self.applog.log_catalog_search(entity_kind="product", filters=filters, rows=rows)
        return rows
