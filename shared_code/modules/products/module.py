"""Product domain module."""

import typing as t

from endow import Domain
from typedal import PaginatedRows, QueryBuilder, TypedRows

from shared_code.data_model import AnyDict, Method, Predicate, Product, ProductEd, Supplier, Tagged
from shared_code.data_model.fields import public_readable_fields, public_readable_values
from shared_code.data_model.validators.is_uuid import is_uuid
from shared_code.infra.database.policy import TypeDALPolicyMixin
from shared_code.modules.auth import AuthContext
from shared_code.modules.catalog_filters import CatalogFilters, ResolvedCatalogFilters
from shared_code.modules.catalog_filters.types import CatalogSortOption
from shared_code.modules.products.policy import ProductPolicy
from shared_code.modules.products.types import ProductDetailPayload
from shared_code.modules.visions import VisionBackend
from shared_code.services import Applogger, CacheService
from shared_code.services.caching import TableDep
from shared_code.util.types import MultiValue

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
    caching: CacheService

    @staticmethod
    def public_product_base_query() -> QueryBuilder[Product]:
        """Return public products without relations; joined tables would make DISTINCT ON ambiguous."""
        return Product.where(Product.available != "verwijderd")

    @classmethod
    def public_catalog_query(cls, catalog_kind: t.Literal["product", "package"] = "product") -> QueryBuilder[Product]:
        """Limit a catalogue tab to its fixed product composition."""
        composition = "package" if catalog_kind == "package" else "single"
        return cls.public_product_base_query().where(Product.composition == composition)

    @classmethod
    def public_product_query(cls, preselect_public: bool = True) -> QueryBuilder[Product]:
        """Return public products with their required method and supplier relations."""
        builder = cls.public_product_base_query().join("method", method="inner").join("supplier", method="inner")
        if preselect_public:
            builder = builder.select(
                *public_readable_fields(Product),
                *public_readable_fields(Method),
                *public_readable_fields(Supplier),
            )

        return builder

    def public_recommendation_candidates(self) -> QueryBuilder[Product]:
        """Return public products eligible for recommendation, with display relations loaded."""
        return self.public_product_query()

    def resolve_public_product_filters(
        self, params: AnyDict | None = None, catalog_kind: t.Literal["product", "package"] | None = None
    ) -> ResolvedCatalogFilters:
        """Resolve request params into product filter state, options included."""
        listing_kind = catalog_kind or "product"
        sort_options = self.public_sort_options(catalog_kind=listing_kind)
        option_builder = self.public_product_base_query()
        if catalog_kind is not None:
            option_builder = self.public_catalog_query(catalog_kind=catalog_kind)

        return self.filters.resolve(
            entity_kind=listing_kind,
            params=params or {},
            option_builder=option_builder,
            sort_options=sort_options,
            exclude_composition=catalog_kind is not None,
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

    def public_sort_options(
        self, catalog_kind: t.Literal["product", "package"] = "product"
    ) -> dict[str, CatalogSortOption[Product]]:
        """Return public product sort options."""
        return self.filters.sort_options(catalog_kind)

    def default_public_sort_option(self) -> CatalogSortOption[Product]:
        """Return the configured default product sort option."""
        return self.filters.default_sort_option("product")

    def public_sort_option(
        self, sort: str, catalog_kind: t.Literal["product", "package"] = "product"
    ) -> CatalogSortOption[Product]:
        """Return the requested sort option, falling back to the configured default."""
        with self.caching("product.sort", catalog_kind, f"{sort=}", scope=None, ttl=300) as cache:
            if cache.valid:
                return CatalogSortOption.from_dillable(cache.value)

            value = self.filters.sort_option(catalog_kind, sort)

            cache.set(value.to_dillable())
            return value

    def list_public_products(
        self,
        filters: ResolvedCatalogFilters | None = None,
        *,
        sort: str,
        page: int,
        limit: int,
        catalog_kind: t.Literal["product", "package"] = "product",
    ) -> PaginatedRows[Product]:
        """Return public products, selecting only public fields."""
        sort_option = self.public_sort_option(sort, catalog_kind=catalog_kind)

        with self.caching(
            "product.list",
            catalog_kind,
            f"{filters=}",
            f"{sort=}",
            f"{page=}",
            f"{limit=}",
            scope=None,
            ttl=300,
            lock=True,
        ) as cache:
            if cache.valid:
                rows = cache.value
                self.applog.log_catalog_search(
                    entity_kind="product",
                    filters=filters,
                    rows=rows,
                    dynamic_sort_ed_id=sort_option.dynamic_sort_ed_id,
                    cache_hit=True,
                )
                return rows

            builder = self.public_catalog_query(catalog_kind=catalog_kind)
            cache.update_deps(TableDep("dynamic_sort"), TableDep("dynamic_filter"), TableDep("school_subject"))
            builder = Product.apply_orderby(sort_option.order, builder)
            builder = self.filters.apply(builder, filters)
            builder = (
                builder.select(*public_readable_fields(Product))
                .join("method", method="inner")
                .select(Method.gid, Method.name, Method.olid)
                .join("supplier", method="inner")
                .select(Supplier.gid, Supplier.name, Supplier.olid)
            )

            rows = builder.paginate(page=page, limit=limit)
            self.applog.log_catalog_search(
                entity_kind="product",
                filters=filters,
                rows=rows,
                dynamic_sort_ed_id=sort_option.dynamic_sort_ed_id,
                cache_hit=False,
            )
            return cache.set(rows)

    def list_public_products_for_comparison(
        self, gids: MultiValue[str], catalog_kind: t.Literal["product", "package"] = "product"
    ) -> TypedRows[Product]:
        """Return selected public products with their comparison relationships."""
        composition = "package" if catalog_kind == "package" else "single"
        return (
            self.public_product_query()
            .where(Product.gid.belongs(gids) & (Product.composition == composition))
            .collect()
        )

    def list_public_products_for_method(self, method_gid: str, exclude_gid: str | None = None) -> TypedRows[Product]:
        """Return current public products belonging to one method."""
        builder = self.public_product_query().where(Product.method_gid == method_gid)
        if exclude_gid:
            builder = builder.where(Product.gid != exclude_gid)
        return builder.collect()

    def list_public_package_components(self, package_gid: str) -> TypedRows[Product]:
        """Return the current public products bundled in one package."""
        component_gids = Tagged.lookup(package_gid, Predicate.BUNDLES, None)

        return self.public_product_query().where(Product.gid.belongs(component_gids)).orderby(Product.name).collect()

    def list_public_parent_packages(self, product_gid: str) -> TypedRows[Product]:
        """Return the current public packages that bundle one product."""
        package_gids = Tagged.lookup(None, Predicate.BUNDLES, product_gid)

        return (
            self.public_product_query()
            .where(Product.gid.belongs(package_gids) & (Product.composition == "package"))
            .orderby(Product.name)
            .collect()
        )

    def get_public_product_detail(
        self, gid: str, referer: str | None = None, from_similar: bool = False
    ) -> ProductDetailPayload | None:
        """Return one public product with direct relations and resolved visions."""
        if not is_uuid(gid):
            return None

        row = self.public_product_query().where(Product.gid == gid).first()
        if row is None:
            return None

        method = row.method
        supplier = row.supplier
        assert method and supplier, "join inner ensures they're not None"

        with self.caching("product.detail", row, method, supplier, scope=None, ttl=300, lock=True) as cache:
            if cache.valid:
                payload, resolved_vision_ids = cache.value
            else:
                cache.update_deps(TableDep("tagged"))
                same_method_products = self.list_public_products_for_method(method.gid, exclude_gid=row.gid)
                package_components = self.list_public_package_components(row.gid)
                parent_packages = self.list_public_parent_packages(row.gid)
                visions_by_gid, vision_ids = self.visions.resolve_public_visions({row.gid: (method, supplier)})
                payload = ProductDetailPayload(
                    product=public_readable_values(row, Product),
                    method=public_readable_values(method, Method),
                    supplier=public_readable_values(supplier, Supplier),
                    same_method_products=[public_readable_values(product, Product) for product in same_method_products],
                    package_components=[public_readable_values(product, Product) for product in package_components],
                    parent_packages=[public_readable_values(product, Product) for product in parent_packages],
                    visions=visions_by_gid[row.gid],
                )
                resolved_vision_ids = [ids[0] for ids in vision_ids.values()]
                cache.set((payload, resolved_vision_ids))
        self.applog.log_catalog_detail(
            entity_kind="product",
            requested_gid=gid,
            row=row,
            vision_ids=resolved_vision_ids,
            referer=referer,
            from_similar=from_similar,
        )
        return payload
