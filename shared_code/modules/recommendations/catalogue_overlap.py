"""Catalogue-field overlap implementation of the recommendation contract."""

import typing as t

from shared_code.data_model import Method, Product
from shared_code.modules.catalog_filters import ResolvedCatalogFilters, any_value_matches
from shared_code.modules.decision_processes import DecisionProcessBackend
from shared_code.modules.methods import MethodBackend
from shared_code.modules.products import ProductBackend

from .contracts import Recommender
from .types import Recommendation, RecommendationResult

MAX_RECOMMENDATIONS_PER_KIND = 9


class CatalogueOverlapRecommender(Recommender):
    """Recommend public catalogue items using the process' current filter fields."""

    decision_processes: DecisionProcessBackend
    methods: MethodBackend
    products: ProductBackend

    def recommend(
        self,
        process_gid: str,
        method_filters: ResolvedCatalogFilters | None = None,
        product_filters: ResolvedCatalogFilters | None = None,
        sort: str = "",
    ) -> RecommendationResult:
        """Return items sharing the process' subjects and levels.

        Products sharing a level-year combination rank ahead of broader matches.
        """
        context = self.decision_processes.get_vision_context(process_gid)
        process = context["process"]
        team = context["team"]
        subjects = process.courses or team.courses or []
        levels = process.levels or team.levels or []
        years: list[str] | None = process.years or team.years
        if not subjects and not levels:
            return RecommendationResult(methods=(), products=())

        process_values = {"subjects": subjects, "levels": levels}
        method_filters = method_filters or self._process_filters(
            self.methods.resolve_public_method_filters, process_values
        )
        product_filters = product_filters or self._process_filters(
            self.products.resolve_public_product_filters, process_values
        )
        methods, method_total = self._recommend_methods(method_filters, subjects, levels, sort=sort)
        products, product_total = self._recommend_products(product_filters, subjects, levels, years, sort=sort)
        return RecommendationResult(
            methods=methods,
            products=products,
            method_total=method_total,
            product_total=product_total,
        )

    @staticmethod
    def _process_filters(
        resolve_filters: t.Callable[..., ResolvedCatalogFilters],
        values: dict[str, list[str]],
    ) -> ResolvedCatalogFilters:
        definitions = resolve_filters({}).filters
        params = {
            definition.slug: values[definition.metadata.field_name]
            for definition in definitions
            if definition.metadata.filter_kind == "dynamic" and definition.metadata.field_name in values
        }
        return resolve_filters(params)

    def _recommend_methods(
        self,
        filters: ResolvedCatalogFilters,
        subjects: list[str],
        levels: list[str],
        sort: str = "",
    ) -> tuple[tuple[Recommendation[Method], ...], int]:
        """Select and describe matching public methods."""
        candidates = self.methods.public_recommendation_candidates()
        candidates = self.methods.filters.apply(candidates, filters)
        if sort and sort in filters.sort_options:
            candidates = Method.apply_orderby(self.methods.public_sort_option(sort).order, candidates)
        else:
            candidates = candidates.orderby(Method.name)
        rows = candidates.paginate(page=1, limit=MAX_RECOMMENDATIONS_PER_KIND)
        recommendations = tuple(
            Recommendation(item=method, reasons=self._reasons(method, subjects, levels)) for method in rows
        )
        return recommendations, rows.pagination["total_items"]

    def _recommend_products(
        self,
        filters: ResolvedCatalogFilters,
        subjects: list[str],
        levels: list[str],
        years: list[str] | None,
        sort: str = "",
    ) -> tuple[tuple[Recommendation[Product], ...], int]:
        """Select matching products, prioritising exact level-year matches."""
        candidates = self.products.public_recommendation_candidates()
        candidates = self.products.filters.apply(candidates, filters)

        level_year_query = any_value_matches(Product.level_x_year, years or [])
        if sort and sort in filters.sort_options:
            ordered = Product.apply_orderby(self.products.public_sort_option(sort).order, candidates)
            products = ordered.paginate(page=1, limit=MAX_RECOMMENDATIONS_PER_KIND)
            total = products.pagination["total_items"]
        elif level_year_query is None:
            products = candidates.orderby(Product.name).paginate(page=1, limit=MAX_RECOMMENDATIONS_PER_KIND)
            total = products.pagination["total_items"]
        else:
            total = candidates.count(distinct=Product.id)
            exact = (
                candidates.where(level_year_query)
                .orderby(Product.name)
                .paginate(page=1, limit=MAX_RECOMMENDATIONS_PER_KIND)
            )
            products = list(exact)
            if remaining := MAX_RECOMMENDATIONS_PER_KIND - len(products):
                # SQL NOT preserves NULL, so missing year metadata needs an explicit branch.
                broader_matches = (Product.level_x_year == None) | ~level_year_query
                products.extend(
                    candidates.where(broader_matches).orderby(Product.name).paginate(page=1, limit=remaining)
                )

        recommendations = tuple(
            Recommendation(
                item=product,
                score=1.0 if set(product.level_x_year or []).intersection(years or []) else 0.0,
                reasons=self._reasons(product, subjects, levels, years=years),
            )
            for product in products
        )
        return recommendations, total

    @staticmethod
    def _reasons(
        item: Method | Product,
        subjects: list[str],
        levels: list[str],
        years: list[str] | None = None,
    ) -> tuple[str, ...]:
        """Describe which temporary catalogue fields caused an item to match."""
        matched_subjects = set(item.subjects or []).intersection(subjects)
        matched_levels = set(item.levels or []).intersection(levels)
        reasons = [f"Vakgebied: {subject}" for subject in sorted(matched_subjects)]
        reasons.extend(f"Niveau: {level}" for level in sorted(matched_levels))
        if isinstance(item, Product):
            matched_level_years = set(item.level_x_year or []).intersection(years or [])
            reasons.extend(f"Niveau en leerjaar: {level_year}" for level_year in sorted(matched_level_years))
        return tuple(reasons)

    @classmethod
    def from_env(cls) -> t.Self:
        """Build the catalogue-overlap implementation without additional configuration."""
        return cls()


__all__ = ["CatalogueOverlapRecommender"]
