"""Method domain module."""

import typing as t

from endow import Domain
from typedal import PaginatedRows, QueryBuilder, TypedRows

from shared_code.data_model import Method, MethodEd, Product, Supplier
from shared_code.data_model.fields import public_readable_values
from shared_code.data_model.validators.is_uuid import is_uuid
from shared_code.infra.database.policy import TypeDALPolicyMixin
from shared_code.modules.auth import AuthContext
from shared_code.modules.catalog_filters import CatalogFilters, ResolvedCatalogFilters
from shared_code.modules.catalog_filters.types import CatalogSortOption
from shared_code.modules.methods.policy import MethodPolicy
from shared_code.modules.methods.types import MethodDetailPayload
from shared_code.modules.products import ProductBackend
from shared_code.modules.visions import VisionBackend
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
    products: ProductBackend
    visions: VisionBackend

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
        builder = Method.apply_orderby(self.public_sort_option(sort).order, builder)
        builder = self.filters.apply(builder, filters)
        builder = builder.join("supplier", method="inner").select(Supplier.gid, Supplier.name)
        builder = builder.join("products", method="inner").select(Product.gid)
        # inner because a method without products is useless

        rows = builder.paginate(page=page, limit=limit)
        self.applog.log_catalog_search(entity_kind="method", filters=filters, rows=rows)
        return rows

    def list_public_methods_for_comparison(self, gids: t.Sequence[str]) -> TypedRows[Method]:
        """Return selected public methods with their comparison relationships."""
        return (
            self._public_method_base_query()
            .where(Method.gid.belongs(gids))
            .join("supplier", method="inner")
            .select(Supplier.gid, Supplier.name, Supplier.olid)
            .join("products", method="inner")
            .select(Product.gid)
            .collect()
        )

    def get_public_method_detail(self, gid: str) -> MethodDetailPayload | None:
        """Return one public method with direct relations and resolved visions."""
        if not is_uuid(gid):
            return None

        row = (
            self._public_method_base_query()
            .where(Method.gid == gid)
            .join("supplier", method="inner")
            .select(Supplier.ALL)
            .first()
        )
        if row is None:
            return None

        supplier = row.supplier
        assert supplier, "join inner ensures it's not None"

        public_products = self.products.list_public_products_for_method(row.gid)
        visions_by_gid, vision_ids = self.visions.resolve_public_visions({row.gid: (row, supplier)})
        resolved_visions = visions_by_gid[row.gid]
        payload = MethodDetailPayload(
            method=public_readable_values(row, Method),
            supplier=public_readable_values(supplier, Supplier),
            products=[public_readable_values(product, Product) for product in public_products],
            visions=resolved_visions,
        )

        self.applog.log_catalog_detail(
            entity_kind="method",
            requested_gid=gid,
            row=row,
            vision_ids=[ids[0] for ids in vision_ids.values()],
        )
        return payload
