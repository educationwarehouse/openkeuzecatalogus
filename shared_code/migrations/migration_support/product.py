"""Product-specific migration manager implementations."""

from edwh_migrate import ViewMigrationManager

from .core import create_effdted_model_view_with_prio_v4, drop_table_or_mv, upsert_index_v1


# noinspection PyPep8Naming
class ProductModelWithPrio_V1(ViewMigrationManager):
    """Manage creation and teardown of the `product_model` helper table."""

    uses = ()

    since = "create_product_ed_20260519_001"

    def up(self) -> None:
        """Create and index the product model view table."""
        create_effdted_model_view_with_prio_v4(self.db, "product")
        upsert_index_v1(
            self.db,
            "product_model",
            ["gid"],
            include=["name", "olid"],
            unique=True,
        )
        upsert_index_v1(
            self.db,
            "product_model",
            ["olid"],
            include=["name", "gid"],
            unique=True,
        )

    def down(self) -> None:
        """Remove product model triggers/functions and drop the model table."""
        self.db.executesql("""
        DROP TRIGGER IF EXISTS refresh_product_model_trigger ON product_ed;
        DROP TRIGGER IF EXISTS product_model_update_trigger ON product_ed;
        """)

        self.db.executesql("""
        DROP FUNCTION IF EXISTS get_active_product(uuid);
        DROP FUNCTION IF EXISTS apply_change_product_model();
        DROP FUNCTION IF EXISTS rebuild_product_model();
        """)
        drop_table_or_mv(self.db, "product_model")
