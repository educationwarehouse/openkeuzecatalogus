"""Migration support manager for `vision_theme_definition_model`."""

from edwh_migrate import ViewMigrationManager

from shared_code.migrations.migration_support import (
    create_effdted_model_view_with_prio_v4,
    drop_table_or_mv,
    upsert_index_v1,
)


# noinspection PyPep8Naming
class VisionThemeDefinitionModelWithPrio_V1(ViewMigrationManager):
    """Manage create/drop operations for the vision-theme-definition model view."""

    uses = ()

    since = "create_vision_theme_definitions_20260824_002"

    def up(self) -> None:
        """Create model-view objects for the effective-dated definitions."""
        create_effdted_model_view_with_prio_v4(self.db, "vision_theme_definition")
        upsert_index_v1(self.db, "vision_theme_definition_model", ["gid"], unique=True)

    def down(self) -> None:
        """Drop model-view objects for the effective-dated definitions."""
        self.db.executesql("""
        DROP TRIGGER IF EXISTS refresh_vision_theme_definition_model_trigger ON vision_theme_definition_ed;
        DROP TRIGGER IF EXISTS vision_theme_definition_model_update_trigger ON vision_theme_definition_ed;
        DROP FUNCTION IF EXISTS get_active_vision_theme_definition(uuid);
        DROP FUNCTION IF EXISTS apply_change_vision_theme_definition_model();
        DROP FUNCTION IF EXISTS rebuild_vision_theme_definition_model();
        """)
        drop_table_or_mv(self.db, "vision_theme_definition_model")
