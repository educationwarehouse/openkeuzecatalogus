"""Learning-material recommendations for completed decision processes."""

from .catalogue_overlap import CatalogueOverlapRecommender
from .contracts import Recommender
from .types import Recommendation, RecommendationResult

__all__ = ["CatalogueOverlapRecommender", "Recommendation", "RecommendationResult", "Recommender"]
