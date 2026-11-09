"""Authorization rules for personal catalog favorites."""

from endow.policy import Allow, AuthorizationResult, Deny
from typedal import QueryBuilder

from shared_code.data_model import CatalogFavorite, CatalogFavoriteEd
from shared_code.infra.database.policy import ReusablePolicy


class FavoritesPolicy(ReusablePolicy):
    """Restrict favorites to their owning user, including for administrators."""

    def _request[T: CatalogFavorite | CatalogFavoriteEd](
        self,
        model: type[T],
    ) -> AuthorizationResult[QueryBuilder[T]]:
        """Return a favorite query scoped to the actor's own records."""
        if self.auth.is_service():
            return Allow(apply=lambda query: query)
        if not self.auth.is_user():
            return Deny("Inloggen is vereist om favorieten te gebruiken.")

        user_gid = self.auth.id
        assert user_gid, "A user actor always has a gid"
        return Allow(apply=lambda query: query.where(lambda favorite: favorite.user_gid == user_gid))

    def request_read(self) -> AuthorizationResult[QueryBuilder[CatalogFavorite]]:
        """Return the current-favorite records visible to the actor."""
        return self._request(CatalogFavorite)

    def request_update(self) -> AuthorizationResult[QueryBuilder[CatalogFavorite]]:
        """Return current favorites the actor may mutate through their history rows."""
        return self._request(CatalogFavorite)

    def request_history(self) -> AuthorizationResult[QueryBuilder[CatalogFavoriteEd]]:
        """Return historical favorite records visible to the actor."""
        return self._request(CatalogFavoriteEd)
