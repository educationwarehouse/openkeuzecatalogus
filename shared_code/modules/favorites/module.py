"""Personal catalog favorite flows."""

import typing as t

from endow import Domain
from typedal import PaginatedRows

from shared_code.data_model import (
    CatalogFavorite,
    CatalogFavoriteEd,
    Method,
    MethodEd,
    Product,
    ProductEd,
    update_effectivedated,
)
from shared_code.data_model.validators.is_uuid import is_uuid
from shared_code.infra.database.policy import TypeDALPolicyMixin
from shared_code.modules.auth import AuthContext
from shared_code.modules.catalog_filters import CatalogEntityKind
from shared_code.modules.favorites.policy import FavoritesPolicy
from shared_code.modules.methods import MethodBackend
from shared_code.modules.products import ProductBackend

from .types import FavoriteItem

if t.TYPE_CHECKING:
    from shared_code.infra.database import DatabaseContext


class FavoritesBackend(Domain, TypeDALPolicyMixin[CatalogFavorite]):
    """Manage personal favorites for public catalog entities."""

    db: DatabaseContext
    auth: AuthContext
    policy: FavoritesPolicy

    @property
    def user_gid(self) -> str:
        """Return the authenticated user identifier required for personal favorites."""
        if not (user_gid := self.auth.id):
            raise PermissionError("Inloggen is vereist om favorieten te gebruiken.")
        return user_gid

    def set_favorite(self, entity_kind: CatalogEntityKind, entity_gid: str, active: bool) -> bool:
        """Set the current user's favorite state and retain effective-dated history."""
        self._validate_entity(entity_kind, entity_gid)
        current = self._current_favorite(entity_kind, entity_gid)

        if active:
            if current:
                return True
            if not self._is_public(entity_kind, entity_gid):
                raise ValueError("Catalogusitem niet gevonden.")

            if historical := self._latest_favorite(entity_kind, entity_gid):
                update_effectivedated(
                    self.db,
                    CatalogFavoriteEd,
                    CatalogFavoriteEd.gid == historical.gid,
                    new_values={},
                    last_saved_by=self._last_saved_by(),
                    allow_deleted_update=True,
                )
            else:
                CatalogFavoriteEd.insert(
                    user_gid=self.user_gid,
                    entity_kind=entity_kind,
                    entity_gid=entity_gid,
                    last_saved_by=self._last_saved_by(),
                )
            self.db.commit()
            return True

        if not current:
            return False

        update_effectivedated(
            self.db,
            CatalogFavoriteEd,
            CatalogFavoriteEd.gid == current.gid,
            last_saved_by=self._last_saved_by(),
            delete=True,
        )
        self.db.commit()
        return False

    def is_favorite(self, entity_kind: CatalogEntityKind, entity_gid: str) -> bool:
        """Return whether the current user has an active favorite for an entity."""
        return self._current_favorite(entity_kind, entity_gid) is not None

    def list_favorites(
        self,
        entity_kind: CatalogEntityKind,
        page: int,
        limit: int = 25,
    ) -> PaginatedRows[CatalogFavorite]:
        """Return one TypeDAL-paginated favorite tab for the current user."""
        self._validate_kind(entity_kind)
        return (
            self.request_read()
            .where(CatalogFavorite.entity_kind == entity_kind)
            .select(CatalogFavorite.ALL, orderby=(~CatalogFavorite.effdt, ~CatalogFavorite.id))
            .paginate(page=page, limit=limit)
        )

    def list_recent(self, limit: int = 10) -> list[FavoriteItem]:
        """Return the newest active favorites across catalog entity types."""
        favorites = (
            self.request_read()
            .select(
                CatalogFavorite.ALL,
                orderby=(~CatalogFavorite.effdt, ~CatalogFavorite.id),
                limitby=(0, limit),
            )
            .collect()
        )
        return self.describe(favorites)

    def describe(self, favorites: t.Iterable[CatalogFavorite]) -> list[FavoriteItem]:
        """Resolve favorite entities into ordered display values without framework URLs."""
        favorite_rows = list(favorites)
        current_names = self._current_names(favorite_rows)
        names = current_names | self._historical_names(favorite_rows, set(current_names))
        return [
            FavoriteItem(
                favorite_gid=favorite.gid,
                entity_kind=t.cast(CatalogEntityKind, favorite.entity_kind),
                entity_gid=favorite.entity_gid,
                name=names.get(self._key(favorite)) or self._unknown_name(favorite.entity_kind),
                favorited_at=favorite.effdt,
                available=self._key(favorite) in current_names,
            )
            for favorite in favorite_rows
        ]

    def _current_favorite(self, entity_kind: CatalogEntityKind, entity_gid: str) -> CatalogFavorite | None:
        """Find an active favorite for one catalog entity in the policy scope."""
        return (
            self.request_read()
            .where((CatalogFavorite.entity_kind == entity_kind) & (CatalogFavorite.entity_gid == entity_gid))
            .select(CatalogFavorite.ALL, limitby=(0, 1))
            .first()
        )

    def _latest_favorite(self, entity_kind: CatalogEntityKind, entity_gid: str) -> CatalogFavoriteEd | None:
        """Find the newest historical version, including a removed favorite."""
        authz = self.policy.request_history().require()
        return (
            authz(CatalogFavoriteEd.permissions(read=True, insert=False, update=False, delete=False))
            .where((CatalogFavoriteEd.entity_kind == entity_kind) & (CatalogFavoriteEd.entity_gid == entity_gid))
            .select(CatalogFavoriteEd.ALL, orderby=(~CatalogFavoriteEd.effdt, ~CatalogFavoriteEd.id), limitby=(0, 1))
            .first()
        )

    @staticmethod
    def _key(favorite: CatalogFavorite) -> tuple[CatalogEntityKind, str]:
        """Return the typed lookup key for one favorite entity."""
        return t.cast(CatalogEntityKind, favorite.entity_kind), favorite.entity_gid

    @staticmethod
    def _unknown_name(entity_kind: str) -> str:
        """Return a safe fallback label for an unavailable catalog entity."""
        return "Onbekend product" if entity_kind == "product" else "Onbekende methode"

    def _gids_by_kind(self, favorites: list[CatalogFavorite]) -> dict[CatalogEntityKind, set[str]]:
        """Group favorite entity identifiers by catalog type."""
        gids: dict[CatalogEntityKind, set[str]] = {"product": set(), "method": set()}
        for favorite in favorites:
            entity_kind, entity_gid = self._key(favorite)
            gids[entity_kind].add(entity_gid)
        return gids

    def _current_names(self, favorites: list[CatalogFavorite]) -> dict[tuple[CatalogEntityKind, str], str]:
        """Load public entity names in one query per catalog type."""
        gids = self._gids_by_kind(favorites)
        names: dict[tuple[CatalogEntityKind, str], str] = {}
        if product_gids := gids["product"]:
            names.update(
                {
                    ("product", product.gid): product.name
                    for product in ProductBackend.public_product_query(preselect_public=False)
                    .where(Product.gid.belongs(product_gids))
                    .select(Product.gid, Product.name)
                    .collect()
                },
            )
        if method_gids := gids["method"]:
            names.update(
                {
                    ("method", method.gid): method.name
                    for method in MethodBackend.public_method_query(preselect_public=False)
                    .where(Method.gid.belongs(method_gids))
                    .select(Method.gid, Method.name)
                    .collect()
                },
            )
        return names

    def _historical_names(
        self,
        favorites: list[CatalogFavorite],
        available: set[tuple[CatalogEntityKind, str]],
    ) -> dict[tuple[CatalogEntityKind, str], str]:
        """Resolve each unavailable entity to its highest-priority latest historical name."""
        gids = self._gids_by_kind(favorites)
        product_gids = {gid for gid in gids["product"] if ("product", gid) not in available}
        method_gids = {gid for gid in gids["method"] if ("method", gid) not in available}
        names: dict[tuple[CatalogEntityKind, str], str] = {}
        if product_gids:
            for product in (
                ProductEd.where(ProductEd.gid.belongs(product_gids))
                .select(
                    ProductEd.gid,
                    ProductEd.name,
                    orderby=(ProductEd.gid, ~ProductEd.prio, ~ProductEd.effdt, ~ProductEd.id),
                )
                .collect()
            ):
                names.setdefault(("product", product.gid), product.name)
        if method_gids:
            for method in (
                MethodEd.where(MethodEd.gid.belongs(method_gids))
                .select(
                    MethodEd.gid,
                    MethodEd.name,
                    orderby=(MethodEd.gid, ~MethodEd.prio, ~MethodEd.effdt, ~MethodEd.id),
                )
                .collect()
            ):
                names.setdefault(("method", method.gid), method.name)
        return names

    @staticmethod
    def _validate_kind(entity_kind: str) -> None:
        """Reject entity kinds outside the catalog's shared literal."""
        if entity_kind not in t.get_args(CatalogEntityKind):
            raise ValueError("Onbekend catalogustype.")

    def _validate_entity(self, entity_kind: CatalogEntityKind, entity_gid: str) -> None:
        """Validate one typed catalog entity identifier."""
        self._validate_kind(entity_kind)
        if not is_uuid(entity_gid):
            raise ValueError("Ongeldig catalogusitem.")

    def _last_saved_by(self) -> str:
        """Return an audit label for the current favorite mutation."""
        return self.auth.get_email() or self.user_gid

    @staticmethod
    def _is_public(entity_kind: CatalogEntityKind, entity_gid: str) -> bool:
        """Return whether an entity remains available in the public catalog."""
        table = Product if entity_kind == "product" else Method
        return table.where((table.gid == entity_gid) & (table.available != "verwijderd")).exists()
