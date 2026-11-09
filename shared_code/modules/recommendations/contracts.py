"""Contract for recommending learning materials for a decision process."""

import abc

from endow import Domain

from shared_code.modules.catalog_filters import ResolvedCatalogFilters

from .types import RecommendationResult


class Recommender(Domain, abc.ABC):
    """Select public catalogue recommendations for one decision process."""

    @abc.abstractmethod
    def recommend(
        self,
        process_gid: str,
        method_filters: ResolvedCatalogFilters | None = None,
        product_filters: ResolvedCatalogFilters | None = None,
        sort: str = "",
    ) -> RecommendationResult:
        """Return the methods and products recommended for `process_gid`."""
        ...

    @classmethod
    def from_env(cls) -> Recommender:
        """Build the recommendation implementation used by this application."""
        from .catalogue_overlap import CatalogueOverlapRecommender

        return CatalogueOverlapRecommender.from_env()


__all__ = ["Recommender"]
