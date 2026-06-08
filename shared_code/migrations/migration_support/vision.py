"""Migration support manager for `vision_model`."""

from edwh_migrate import ViewMigrationManager

from shared_code.migrations.migration_support import (
    create_effdted_model_view_with_prio_v4,
    drop_table_or_mv,
    upsert_index_v1,
)


# noinspection PyPep8Naming
class VisionModelWithPrio_V1(ViewMigrationManager):
    """Manage create/drop operations for the prioritized vision model view."""

    uses = ()

    since = "create_vision_ed_20260525_001"

    def up(self) -> None:
        """Create view/index objects for the vision model."""
        create_effdted_model_view_with_prio_v4(self.db, "vision")
        upsert_index_v1(
            self.db,
            "vision_model",
            ["gid"],
            unique=True,
        )
        upsert_index_v1(
            self.db,
            "vision_model",
            ["olid", "onderwijskwaliteit"],
            unique=True,
        )

    def down(self) -> None:
        """Drop view/index objects for the vision model."""
        self.db.executesql("""
        DROP TRIGGER IF EXISTS refresh_vision_model_trigger ON vision_ed;
        """)

        self.db.executesql("""
        DROP FUNCTION IF EXISTS get_active_vision;
        """)
        drop_table_or_mv(self.db, "vision_model")
