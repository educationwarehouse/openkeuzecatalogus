"""Migration support manager for `tagged_model`."""

from edwh_migrate import ViewMigrationManager

from .core import create_effdted_model_view_with_prio_v4, drop_table_or_mv, upsert_index_v1


# noinspection PyPep8Naming
class TaggedModelWithPrio_V1(ViewMigrationManager):
    """Manage create/drop operations for the prioritized tagged model view."""

    uses = ()

    since = "create_tagged_ed_20260622_001"

    def up(self) -> None:
        """Create view/index objects for the tagged model."""
        create_effdted_model_view_with_prio_v4(self.db, "tagged")
        upsert_index_v1(
            self.db,
            "tagged_model",
            ["gid"],
            include=["subject_gid", "predicate", "object_gid"],
            unique=True,
        )
        upsert_index_v1(
            self.db,
            "tagged_model",
            ["subject_gid"],
            include=["predicate", "object_gid"],
        )
        upsert_index_v1(
            self.db,
            "tagged_model",
            ["object_gid"],
            include=["predicate", "subject_gid"],
        )
        upsert_index_v1(
            self.db,
            "tagged_model",
            ["subject_gid", "predicate", "object_gid"],
            include=["gid"],
            unique=True,
        )

    def down(self) -> None:
        """Drop view/index objects for the tagged model."""
        self.db.executesql("""
        DROP TRIGGER IF EXISTS refresh_tagged_model_trigger ON tagged_ed;
        DROP TRIGGER IF EXISTS tagged_model_update_trigger ON tagged_ed;
        """)

        self.db.executesql("""
        DROP FUNCTION IF EXISTS get_active_tagged(uuid);
        DROP FUNCTION IF EXISTS apply_change_tagged_model();
        DROP FUNCTION IF EXISTS rebuild_tagged_model();
        """)
        drop_table_or_mv(self.db, "tagged_model")
