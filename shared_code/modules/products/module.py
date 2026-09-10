"""Product domain module."""

import typing as t

from endow import Domain
from typedal import PaginatedRows, QueryBuilder, TypedRows

from shared_code.data_model import AnyDict, Method, Product, ProductEd, Supplier
from shared_code.data_model.fields import public_readable_values
from shared_code.data_model.validators.is_uuid import is_uuid
from shared_code.infra.database.policy import TypeDALPolicyMixin
from shared_code.modules.auth import AuthContext
from shared_code.modules.catalog_filters import CatalogFilters, ResolvedCatalogFilters
from shared_code.modules.catalog_filters.types import CatalogSortOption
from shared_code.modules.products.policy import ProductPolicy
from shared_code.modules.products.types import ProductDetailPayload
from shared_code.modules.visions import VisionBackend
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
    visions: VisionBackend

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

    @t.overload
    def list_my_products(self, with_deleted: t.Literal[False] = False) -> QueryBuilder[Product]: ...

    @t.overload
    def list_my_products(self, with_deleted: t.Literal[True]) -> QueryBuilder[ProductEd]: ...

    def list_my_products(self, with_deleted: bool = False) -> QueryBuilder[Product] | QueryBuilder[ProductEd]:
        """Return products visible to the current actor, optionally including deleted versions."""
        if with_deleted:
            authz = self.policy.request_read_with_deleted().require()
            builder = ProductEd.permissions(read=True, insert=False, update=False, delete=False)
            return authz(builder)
        else:
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
        builder = Product.apply_orderby(self.public_sort_option(sort).order, builder)
        builder = self.filters.apply(builder, filters)
        builder = builder.join("method", method="inner").select(Method.gid, Method.name)
        builder = builder.join("supplier", method="inner").select(Supplier.gid, Supplier.name)

        rows = builder.paginate(page=page, limit=limit)
        self.applog.log_catalog_search(entity_kind="product", filters=filters, rows=rows)
        return rows

    def list_public_products_for_comparison(self, gids: t.Sequence[str]) -> TypedRows[Product]:
        """Return selected public products with their comparison relationships."""
        return (
            self._public_product_base_query()
            .where(Product.gid.belongs(gids))
            .join("method", method="inner")
            .select(Method.gid, Method.name, Method.olid)
            .join("supplier", method="inner")
            .select(Supplier.gid, Supplier.name, Supplier.olid)
            .collect()
        )

    def list_public_products_for_method(self, method_gid: str) -> TypedRows[Product]:
        """Return all current public products belonging to one method."""
        return self._public_product_base_query().where(Product.method_gid == method_gid).collect()

    def get_public_product_detail(self, gid: str) -> ProductDetailPayload | None:
        """Return one public product with direct relations and resolved visions."""
        if not is_uuid(gid):
            return None

        row = (
            self._public_product_base_query()
            .where(Product.gid == gid)
            .join("method", method="inner")
            .select(Method.ALL)
            .join("supplier", method="inner")
            .select(Supplier.ALL)
            .first()
        )
        if row is None:
            return None

        method = row.method
        supplier = row.supplier
        assert method and supplier, "join inner ensures they're not None"

        visions_by_gid, vision_ids = self.visions.resolve_public_visions({row.gid: (method, supplier)})
        resolved_visions = visions_by_gid[row.gid]
        payload = ProductDetailPayload(
            product=public_readable_values(row, Product),
            method=public_readable_values(method, Method),
            supplier=public_readable_values(supplier, Supplier),
            visions=resolved_visions,
        )

        self.applog.log_catalog_detail(
            entity_kind="product",
            requested_gid=gid,
            row=row,
            vision_ids=[ids[0] for ids in vision_ids.values()],
        )
        return payload
