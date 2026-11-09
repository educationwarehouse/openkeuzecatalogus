"""Product field representer helpers."""

import typing as t

from shared_code.data_model.constants import PRODUCT_COMPOSITION_LABELS


def product_composition(value: str, *_: t.Any) -> str:
    """Render a product-composition code using its maintained Dutch label."""
    return PRODUCT_COMPOSITION_LABELS.get(value, value)
