"""Read and persist reusable catalogue settings."""

import json
import typing as t

from endow import Domain

from shared_code.data_model import CatalogusSetting
from shared_code.modules.auth import AuthContext

if t.TYPE_CHECKING:
    from shared_code.infra.database import DatabaseContext

CATALOG_SHOW_THEMES_KEY = "catalog.show_themes"


class CatalogusSettings(Domain):
    """Share keyed JSON settings across catalogue features."""

    db: DatabaseContext
    auth: AuthContext

    def get_show_themes(self) -> bool:
        """Show catalogue themes unless they have explicitly been disabled."""
        return self.get(CATALOG_SHOW_THEMES_KEY, default=True) is not False

    def save_show_themes(self, value: bool) -> None:
        """Persist theme visibility without changing the underlying vision data."""
        self.set(CATALOG_SHOW_THEMES_KEY, value=value)

    @staticmethod
    def get(key: str, default: object = None) -> object:
        """Return the stored value or the caller's default when absent."""
        setting = CatalogusSetting.where(CatalogusSetting.key == key).first()
        return setting.value if setting is not None else default

    def set(self, key: str, value: object) -> None:
        """Persist a JSON value while preserving its GID and creation time."""
        if not (self.auth.is_service() or self.auth.is_admin()):
            raise PermissionError("Only admins and services may save catalogue settings")

        # Validate JSON compatibility; pyDAL serializes the native value for storage.
        json.dumps(value, allow_nan=False)
        row, errors = CatalogusSetting.validate_and_update_or_insert(CatalogusSetting.key == key, key=key, value=value)
        if errors:
            self.db.rollback()
            raise ValueError(next(iter(errors.values())))
        elif row is None:
            self.db.rollback()
            raise ValueError("De catalogusinstelling kon niet worden opgeslagen.")
        self.db.commit()
