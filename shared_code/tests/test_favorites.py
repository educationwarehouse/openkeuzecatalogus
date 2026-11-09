"""Tests for personal catalog favorites."""

import typing as t

from typedal import TypeDAL

from shared_code.data_model import AuthUser, MethodEd, ProductEd, Supplier
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.favorites import FavoritesBackend


def _make_backend(auth_adapter: AuthAdapter, db: TypeDAL) -> FavoritesBackend:
    """Construct a favorites backend with its real policy dependencies."""
    return FavoritesBackend.with_injected(db=db, auth_adapter=auth_adapter)


def test_favorites_are_personal_and_can_be_removed_and_restored(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    auth_user_factory: t.Callable[..., AuthUser],
    auth_adapter_factory: t.Callable[..., AuthAdapter],
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
) -> None:
    """A favorite is isolated per user and survives an effective-dated restoration."""
    assert migrated_db_per_file is None
    supplier = supplier_factory(name="Favorites supplier", email_domains=["favorites.example.test"])
    method = method_factory(
        supplier_gid=supplier.gid,
        olid="favorites-method",
        name="Favorites method",
    )
    product = product_factory(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="favorites-product",
        name="Favorites product",
    )
    user = auth_user_factory(prefix="favorite-owner")
    other_user = auth_user_factory(prefix="favorite-other")
    backend = _make_backend(auth_adapter_factory(user), db_per_file)
    other_backend = _make_backend(auth_adapter_factory(other_user), db_per_file)

    assert backend.set_favorite("product", product.gid, True) is True
    assert backend.is_favorite("product", product.gid) is True
    assert [item.name for item in backend.list_recent()] == ["Favorites product"]
    assert other_backend.list_recent() == []

    assert backend.set_favorite("product", product.gid, False) is False
    assert backend.is_favorite("product", product.gid) is False
    assert backend.set_favorite("product", product.gid, True) is True

    items = backend.describe(backend.list_favorites("product", page=1, limit=10))
    assert [(item.entity_gid, item.available) for item in items] == [(product.gid, True)]
