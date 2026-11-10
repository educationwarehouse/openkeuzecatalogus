"""Migration support manager for `supplier_model`."""

from edwh_migrate import ViewMigrationManager

from shared_code.migrations.migration_support import (
    create_effdted_model_view_with_prio_v4,
    create_trigram_index_v1,
    drop_table_or_mv,
    upsert_index_v1,
)


# noinspection PyPep8Naming
class SupplierModelWithPrio_V1(ViewMigrationManager):
    """Manage create/drop operations for the prioritized supplier model view."""

    uses = ()

    since = "create_supplier_ed_20260521_001"

    def up(self) -> None:
        """Create view/index objects for the supplier model."""
        create_effdted_model_view_with_prio_v4(self.db, "supplier")
        upsert_index_v1(
            self.db,
            "supplier_model",
            ["gid"],
            include=["name", "olid"],
            unique=True,
        )
        upsert_index_v1(
            self.db,
            "supplier_model",
            ["olid"],
            include=["name", "gid"],
            unique=True,
        )
        create_trigram_index_v1(self.db, "supplier_model", "name")
        create_trigram_index_v1(self.db, "supplier_model", "olid")

    def down(self) -> None:
        """Drop view/index objects for the supplier model."""
        self.db.executesql("""
        DROP TRIGGER IF EXISTS refresh_supplier_model_trigger ON supplier_ed;
        DROP TRIGGER IF EXISTS supplier_model_update_trigger ON supplier_ed;
        """)

        self.db.executesql("""
        DROP FUNCTION IF EXISTS get_active_supplier(uuid);
        DROP FUNCTION IF EXISTS apply_change_supplier_model();
        DROP FUNCTION IF EXISTS rebuild_supplier_model();
        """)
        drop_table_or_mv(self.db, "supplier_model")
