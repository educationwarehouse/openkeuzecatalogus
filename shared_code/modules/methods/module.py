"""Method domain module."""

import typing as t

from endow import Domain
from typedal import PaginatedRows, QueryBuilder, TypedRows

from shared_code.data_model import AnyDict, Method, MethodEd, Product, Supplier
from shared_code.data_model.fields import public_readable_fields, public_readable_values
from shared_code.data_model.validators.is_uuid import is_uuid
from shared_code.infra.database.policy import TypeDALPolicyMixin
from shared_code.modules.auth import AuthContext
from shared_code.modules.catalog_filters import CatalogFilters, ResolvedCatalogFilters
from shared_code.modules.catalog_filters.types import CatalogSortOption
from shared_code.modules.methods.policy import MethodPolicy
from shared_code.modules.methods.types import MethodDetailPayload
from shared_code.modules.products import ProductBackend
from shared_code.modules.visions import VisionBackend
from shared_code.services import Applogger, CacheService
from shared_code.services.caching import TableDep
from shared_code.util.types import MultiValue

if t.TYPE_CHECKING:
    from shared_code.infra.database import DatabaseContext


class MethodBackend(Domain, TypeDALPolicyMixin[Method]):
    """Method business flows and RBAC orchestration."""

    db: DatabaseContext
    auth: AuthContext
    policy: MethodPolicy
    filters: CatalogFilters
    applog: Applogger
    products: ProductBackend
    visions: VisionBackend
    caching: CacheService

    @staticmethod
    def public_method_base_query() -> QueryBuilder[Method]:
        """Return public methods without relations; joined tables would make DISTINCT ON ambiguous."""
        return Method.where(Method.available != "verwijderd")

    @classmethod
    def public_method_query(cls, preselect_public: bool = True) -> QueryBuilder[Method]:
        """Return public methods with their required supplier relation."""
        builder = cls.public_method_base_query().join("supplier", method="inner")
        if preselect_public:
            builder = builder.select(
                *public_readable_fields(Method),
                *public_readable_fields(Supplier),
            )
        return builder

    @staticmethod
    def _with_public_relations(builder: QueryBuilder[Method]) -> QueryBuilder[Method]:
        """Load the relations shared by public method consumers."""
        return (
            builder.join("supplier", method="inner")
            .select(Supplier.gid, Supplier.name, Supplier.olid)
            .join(Method.products, method="inner")
            # TypeDAL 6 resolves Product to the joined alias, avoiding a cross join.
            .where(Product.available != "verwijderd")
            .select(Product.gid)
        )

    def public_recommendation_candidates(self) -> QueryBuilder[Method]:
        """Return public methods eligible for recommendation, with display relations loaded."""
        return self._with_public_relations(self.public_method_query())

    def resolve_public_method_filters(self, params: AnyDict | None = None) -> ResolvedCatalogFilters:
        """Resolve request params into method filter state."""
        sort_options = self.public_sort_options()
        return self.filters.resolve(
            entity_kind="method",
            params=params or {},
            option_builder=self.public_method_base_query(),
            sort_options=sort_options,
        )

    @t.overload
    def list_my_methods(self, with_deleted: t.Literal[False] = False) -> QueryBuilder[Method]: ...

    @t.overload
    def list_my_methods(self, with_deleted: t.Literal[True]) -> QueryBuilder[MethodEd]: ...

    def list_my_methods(self, with_deleted: bool = False) -> QueryBuilder[Method] | QueryBuilder[MethodEd]:
        """Return methods visible to the current actor, optionally including deleted versions."""
        if with_deleted:
            authz = self.policy.request_read_with_deleted().require()
            builder = MethodEd.permissions(read=True, insert=False, update=False, delete=False)
            return authz(builder)
        else:
            return self.request_read()

    def public_sort_options(self) -> dict[str, CatalogSortOption[Method]]:
        """Return public method sort options."""
        return self.filters.sort_options("method")

    def default_public_sort_option(self) -> CatalogSortOption[Method]:
        """Return the configured default method sort option."""
        return self.filters.default_sort_option("method")

    def public_sort_option(self, sort: str) -> CatalogSortOption[Method]:
        """Return the requested sort option, falling back to the configured default."""
        with self.caching("method.sort", f"{sort=}", scope=None, ttl=300) as cache:
            if cache.valid:
                return CatalogSortOption.from_dillable(cache.value)

            value = self.filters.sort_option("method", sort)

            cache.set(value.to_dillable())
            return value

    def list_public_methods(
        self,
        filters: ResolvedCatalogFilters | None = None,
        *,
        sort: str,
        page: int,
        limit: int,
    ) -> PaginatedRows[Method]:
        """Return public methods, selecting only public fields."""
        # cached internally:
        sort_option = self.public_sort_option(sort)

        with self.caching(
            "method.list", f"{filters=}", f"{sort=}", f"{page=}", f"{limit=}", scope=None, ttl=300, lock=True
        ) as cache:
            if cache.valid:
                rows = cache.value

                self.applog.log_catalog_search(
                    entity_kind="method",
                    filters=filters,
                    rows=rows,
                    dynamic_sort_ed_id=sort_option.dynamic_sort_ed_id,
                    cache_hit=True,
                )

                return rows

            builder = self.public_method_base_query().select(*public_readable_fields(Method))
            cache.update_deps(TableDep("dynamic_sort"), TableDep("dynamic_filter"), TableDep("school_subject"))
            builder = Method.apply_orderby(sort_option.order, builder)
            builder = self.filters.apply(builder, filters)
            builder = self._with_public_relations(builder)
            # inner because a method without products is useless

            rows = builder.paginate(page=page, limit=limit)
            self.applog.log_catalog_search(
                entity_kind="method",
                filters=filters,
                rows=rows,
                dynamic_sort_ed_id=sort_option.dynamic_sort_ed_id,
                cache_hit=False,
            )

            return cache.set(rows)

    def list_public_methods_for_comparison(self, gids: MultiValue[str]) -> TypedRows[Method]:
        """Return selected public methods with their comparison relationships."""
        builder = self.public_method_query().where(Method.gid.belongs(gids))
        return self._with_public_relations(builder).collect()

    def get_public_method_detail(
        self, gid: str, referer: str | None = None, from_similar: bool = False
    ) -> MethodDetailPayload | None:
        """Return one public method with direct relations and resolved visions."""
        if not is_uuid(gid):
            return None

        row = self.public_method_query().where(Method.gid == gid).first()
        if row is None:
            return None

        supplier = row.supplier
        assert supplier, "join inner ensures it's not None"

        with self.caching("method.detail", row, supplier, scope=None, ttl=300, lock=True) as cache:
            if cache.valid:
                payload, resolved_vision_ids = cache.value
            else:
                public_products = self.products.list_public_products_for_method(row.gid)
                visions_by_gid, vision_ids = self.visions.resolve_public_visions({row.gid: (row, supplier)})
                payload = MethodDetailPayload(
                    method=public_readable_values(row, Method),
                    supplier=public_readable_values(supplier, Supplier),
                    products=[public_readable_values(product, Product) for product in public_products],
                    visions=visions_by_gid[row.gid],
                )
                resolved_vision_ids = [ids[0] for ids in vision_ids.values()]
                cache.set((payload, resolved_vision_ids))
        self.applog.log_catalog_detail(
            entity_kind="method",
            requested_gid=gid,
            row=row,
            vision_ids=resolved_vision_ids,
            referer=referer,
            from_similar=from_similar,
        )
        return payload
