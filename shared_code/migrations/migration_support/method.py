"""Migration support manager for `method_model`."""

from edwh_migrate import ViewMigrationManager

from shared_code.migrations.migration_support import (
    create_effdted_model_view_with_prio_v4,
    drop_table_or_mv,
    upsert_index_v1,
)


# noinspection PyPep8Naming
class MethodModelWithPrio_V1(ViewMigrationManager):
    """Manage create/drop operations for the prioritized method model view."""

    uses = ()

    since = "create_method_ed_20260521_001"

    def up(self) -> None:
        """Create view/index objects for the method model."""
        create_effdted_model_view_with_prio_v4(self.db, "method")
        upsert_index_v1(
            self.db,
            "method_model",
            ["gid"],
            include=["name", "olid"],
            unique=True,
        )
        upsert_index_v1(
            self.db,
            "method_model",
            ["olid"],
            include=["name", "gid"],
            unique=True,
        )
        # ...

    def down(self) -> None:
        """Drop view/index objects for the method model."""
        self.db.executesql("""
        DROP TRIGGER IF EXISTS refresh_method_model_trigger ON method_ed;
        """)

        self.db.executesql("""
        DROP FUNCTION IF EXISTS get_active_method;
        """)
        drop_table_or_mv(self.db, "method_model")
