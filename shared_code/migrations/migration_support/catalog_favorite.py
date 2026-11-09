"""Migration support for the current catalog-favorite projection."""

from edwh_migrate import ViewMigrationManager

from shared_code.migrations.migration_support.core import (
    create_effdted_model_view_with_prio_v4,
    drop_table_or_mv,
    upsert_index_v1,
)


# noinspection PyPep8Naming
class CatalogFavoriteModelWithPrio_V1(ViewMigrationManager):
    """Manage create and drop operations for current catalog favorites."""

    uses = ()

    since = "create_catalog_favorites_20260922_001"

    def up(self) -> None:
        """Create the current favorite projection and its lookup indexes."""
        create_effdted_model_view_with_prio_v4(self.db, "catalog_favorite")
        upsert_index_v1(self.db, "catalog_favorite_model", ["gid"], unique=True)
        upsert_index_v1(
            self.db,
            "catalog_favorite_model",
            ["user_gid", "entity_kind", "entity_gid"],
            unique=True,
        )
        upsert_index_v1(
            self.db,
            "catalog_favorite_model",
            ["user_gid", "entity_kind", "effdt DESC", "id DESC"],
        )

    def down(self) -> None:
        """Drop the current favorite projection and trigger functions."""
        self.db.executesql("""
        DROP TRIGGER IF EXISTS refresh_catalog_favorite_model_trigger ON catalog_favorite_ed;
        DROP TRIGGER IF EXISTS catalog_favorite_model_update_trigger ON catalog_favorite_ed;
        DROP FUNCTION IF EXISTS get_active_catalog_favorite(uuid);
        DROP FUNCTION IF EXISTS apply_change_catalog_favorite_model();
        DROP FUNCTION IF EXISTS rebuild_catalog_favorite_model();
        """)
        drop_table_or_mv(self.db, "catalog_favorite_model")
