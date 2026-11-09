"""Effective-dated personal catalog favorites."""

import typing as t

from pydal.validators import IS_IN_SET
from typedal import Ref, relationship
from typedal.fields import TypedField

from shared_code.data_model.fields import UUIDReferenceField
from shared_code.data_model.tables.base import EffdtTable

if t.TYPE_CHECKING:
    from shared_code.data_model import AuthUser, Method, Product  # noqa: F401 - used in relationship


class CatalogFavoriteEd(EffdtTable):
    """Historical favorite state for one user and catalog entity."""

    user_gid = UUIDReferenceField(label="Gebruiker")
    entity_kind = TypedField(str, length=20, label="Type", requires=IS_IN_SET(("product", "method")))
    entity_gid = UUIDReferenceField(label="Catalogusitem")


class CatalogFavorite(CatalogFavoriteEd):
    """Current active catalog favorite projection."""

    user = relationship(Ref["AuthUser"], lambda favorite, user: favorite.user_gid == user.gid)
    product = relationship(
        Ref["Product"],
        lambda favorite, product: (favorite.entity_kind == "product") & (favorite.entity_gid == product.gid),
    )
    method = relationship(
        Ref["Method"],
        lambda favorite, method: (favorite.entity_kind == "method") & (favorite.entity_gid == method.gid),
    )
