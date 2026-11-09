"""Read model that merges catalog products and methods for material selection."""

import typing as t

from typedal import Ref, TypedTable, relationship
from typedal.fields import TypedField

if t.TYPE_CHECKING:
    from shared_code.data_model import Method, Product  # noqa F401 - used in relationship


class LearningMaterial(TypedTable):
    """A searchable product or method exposed through the catalog selection view."""

    name = TypedField(str, length=255, label="Naam")
    olid = TypedField(str, length=255, label="OLID")
    origin = TypedField(str, length=10, label="Herkomst")

    product = relationship(Ref["Product"], lambda lm, product: lm.olid == product.olid, join="left")
    method = relationship(Ref["Method"], lambda lm, method: lm.olid == method.olid, join="left")
