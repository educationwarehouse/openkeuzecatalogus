"""Typed payloads for public method pages."""

import typing as t

from shared_code.generated.public_payloads import PublicMethod, PublicProduct, PublicSupplier
from shared_code.modules.visions import ResolvedVision


class MethodDetailPayload(t.TypedDict):
    """A public method with one direct relationship level."""

    method: PublicMethod
    supplier: PublicSupplier
    products: list[PublicProduct]
    visions: list[ResolvedVision]
