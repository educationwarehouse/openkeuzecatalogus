"""Typed payloads for public product pages."""

import typing as t

from shared_code.generated.public_payloads import PublicMethod, PublicProduct, PublicSupplier
from shared_code.modules.visions import ResolvedVision


class ProductDetailPayload(t.TypedDict):
    """A public product with one direct relationship level."""

    product: PublicProduct
    method: PublicMethod
    supplier: PublicSupplier
    visions: list[ResolvedVision]
