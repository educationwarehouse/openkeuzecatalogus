"""Stable outputs for learning-material recommendation strategies."""

import dataclasses as dc

from shared_code.data_model import Method, Product


@dc.dataclass(frozen=True, slots=True)
class Recommendation[T]:
    """One recommended catalogue item with optional ranking metadata."""

    item: T
    score: float | None = None
    reasons: tuple[str, ...] = ()


@dc.dataclass(frozen=True, slots=True)
class RecommendationResult:
    """Methods and products selected for one completed decision process."""

    methods: tuple[Recommendation[Method], ...]
    products: tuple[Recommendation[Product], ...]
    method_total: int | None = None
    product_total: int | None = None


__all__ = ["Recommendation", "RecommendationResult"]
