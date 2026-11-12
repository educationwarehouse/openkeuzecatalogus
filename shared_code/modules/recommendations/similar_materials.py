"""Find alternatives for public catalogue detail pages."""

import typing as t

from endow import Domain
from typedal import PaginatedRows, QueryBuilder
from typedal.types import OrderBy

from shared_code.data_model import Method, Product
from shared_code.data_model.constants.catalog import CatalogListingKind
from shared_code.generated.public_payloads import PublicMethod, PublicProduct
from shared_code.modules.catalog_filters import CatalogEntityKind, any_value_matches
from shared_code.modules.catalogus_settings import CatalogusSettings
from shared_code.modules.methods import MethodBackend
from shared_code.modules.products import ProductBackend
from shared_code.services import Applogger, CacheService

if t.TYPE_CHECKING:
    from shared_code.infra.database import DatabaseContext

SIMILAR_MATERIAL_LIMIT_KEY = "catalog.similar_material_limit"
DEFAULT_SIMILAR_MATERIAL_LIMIT = 9


class SimilarMaterials(Domain):
    """Rank alternatives by subject and level overlap, then supplier."""

    methods: MethodBackend
    products: ProductBackend
    applog: Applogger
    caching: CacheService
    settings: CatalogusSettings
    db: DatabaseContext

    def get_limit(self) -> int:
        """Read the current global limit without caching the setting."""
        value = self.settings.get(SIMILAR_MATERIAL_LIMIT_KEY, default=DEFAULT_SIMILAR_MATERIAL_LIMIT)
        if type(value) is int and value >= 1:
            return value
        return DEFAULT_SIMILAR_MATERIAL_LIMIT

    def save_limit(self, value: str) -> None:
        """Validate and persist the global limit for admins and services."""
        try:
            limit = int(value)
        except ValueError as exc:
            raise ValueError("Vul een geheel getal van minimaal 1 in.") from exc
        if limit < 1:
            raise ValueError("Vul een geheel getal van minimaal 1 in.")
        self.settings.set(SIMILAR_MATERIAL_LIMIT_KEY, value=limit)

    def for_product(
        self, source: PublicProduct, catalog_kind: t.Literal["product", "package"] = "product"
    ) -> PaginatedRows[Product]:
        """Return other public products of the same catalogue tab sharing a subject and a level."""
        composition = "package" if catalog_kind == "package" else "single"
        candidates = self.products.public_recommendation_candidates().where(Product.composition == composition)
        return self._find(Product, candidates, source, entity_kind="product", catalog_kind=catalog_kind)

    def for_method(self, source: PublicMethod) -> PaginatedRows[Method]:
        """Return other public methods sharing a subject."""
        return self._find(Method, self.methods.public_recommendation_candidates(), source, entity_kind="method")

    def _find[T: Method | Product](
        self,
        table: type[T],
        candidates: QueryBuilder[T],
        source: PublicMethod | PublicProduct,
        entity_kind: CatalogEntityKind,
        catalog_kind: CatalogListingKind | None = None,
    ) -> PaginatedRows[T]:
        subjects = sorted(set(source.get("subjects") or []) - {""})
        levels = sorted(set(source.get("levels") or []) - {""})
        source_gid = source["gid"]
        supplier_gid = source.get("supplier_gid")
        limit = self.get_limit()
        day = table.__search_mixin_daily_seed__()
        with self.caching(
            "catalog.similar",
            f"{entity_kind=}",
            f"{catalog_kind=}",
            f"{source_gid=}",
            f"{subjects=}",
            f"{levels=}",
            f"{supplier_gid=}",
            f"{day=}",
            f"{limit=}",
            scope=None,
            ttl=300,
            lock=True,
        ) as cache:
            cache_hit = cache.valid
            if cache_hit:
                rows = cache.value
            else:
                subject_query = any_value_matches(table.subjects, subjects)
                level_query = any_value_matches(table.levels, levels)
                if subject_query is None or (entity_kind == "product" and level_query is None):
                    candidates = candidates.where(table.id == 0)
                else:
                    candidates = candidates.where(subject_query).where(table.gid != source_gid)
                    if entity_kind == "product" and level_query is not None:
                        candidates = candidates.where(level_query)

                rank_parts = [
                    f"CASE WHEN {field.contains(value)} THEN 2 ELSE 0 END"
                    for field, values in ((table.subjects, subjects), (table.levels, levels))
                    for value in values
                ]
                if supplier_gid:
                    rank_parts.append(f"CASE WHEN {table.supplier_gid == supplier_gid} THEN 1 ELSE 0 END")
                rank_expression = " + ".join(rank_parts) or "0"
                rank_order = ~self.db.sql_expression(rank_expression.replace("%", "%%"), output_type="integer")
                candidates = table.apply_orderby("random", candidates)
                candidates = candidates.select(
                    f"({rank_expression}) AS similarity_rank",
                    orderby=t.cast(OrderBy | t.Iterable[OrderBy], (rank_order, candidates.select_kwargs["orderby"])),
                )
                rows = candidates.paginate(page=1, limit=limit)
                cache.set(rows)

            self.applog.log_catalog_search(
                entity_kind=entity_kind,
                rows=t.cast(PaginatedRows[T], rows),
                cache_hit=cache_hit,
                filters=None,
                dynamic_sort_ed_id=None,
                search_type="similar",
                source_gid=source_gid,
                suggestion_limit=limit,
            )
            return rows
