"""Product-specific data-model constants."""

from typing import Literal

MaterialType = Literal["bought", "created", "other"]

PRODUCT_COMPOSITION_LABELS = {
    "package": "Productpakket",
    "single": "Los product",
    "component": "Onderdeel (niet los verkrijgbaar)",
}
