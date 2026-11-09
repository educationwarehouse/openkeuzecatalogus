"""Migration managers for effective-dated catalogue-search settings."""

from edwh_migrate import ViewMigrationManager

from .core import create_effdted_model_view_with_prio_v4, drop_table_or_mv, upsert_index_v1


# noinspection PyPep8Naming
class DynamicFilterModelWithPrio_V1(ViewMigrationManager):
    """Manage the current dynamic-filter model."""

    uses = ()

    since = "create_effective_dated_dynamic_filters_20260831_001"

    def up(self) -> None:
        """Create the current dynamic-filter model and indexes."""
        create_effdted_model_view_with_prio_v4(self.db, "dynamic_filter")
        upsert_index_v1(self.db, "dynamic_filter_model", ["gid"], unique=True)
        upsert_index_v1(self.db, "dynamic_filter_model", ["slug"], unique=True)

    def down(self) -> None:
        """Drop the dynamic-filter model and its supporting objects."""
        self.db.executesql("""
        DROP TRIGGER IF EXISTS refresh_dynamic_filter_model_trigger ON dynamic_filter_ed;
        DROP TRIGGER IF EXISTS dynamic_filter_model_update_trigger ON dynamic_filter_ed;
        DROP FUNCTION IF EXISTS get_active_dynamic_filter(uuid);
        DROP FUNCTION IF EXISTS apply_change_dynamic_filter_model();
        DROP FUNCTION IF EXISTS rebuild_dynamic_filter_model();
        """)
        drop_table_or_mv(self.db, "dynamic_filter_model")


# noinspection PyPep8Naming
class DynamicSortModelWithPrio_V1(ViewMigrationManager):
    """Manage the current dynamic-sort model."""

    uses = ()

    since = "create_effective_dated_dynamic_sorts_20260831_002"

    def up(self) -> None:
        """Create the current dynamic-sort model and indexes."""
        create_effdted_model_view_with_prio_v4(self.db, "dynamic_sort")
        upsert_index_v1(self.db, "dynamic_sort_model", ["gid"], unique=True)
        upsert_index_v1(self.db, "dynamic_sort_model", ["slug"], unique=True)

    def down(self) -> None:
        """Drop the dynamic-sort model and its supporting objects."""
        self.db.executesql("""
        DROP TRIGGER IF EXISTS refresh_dynamic_sort_model_trigger ON dynamic_sort_ed;
        DROP TRIGGER IF EXISTS dynamic_sort_model_update_trigger ON dynamic_sort_ed;
        DROP FUNCTION IF EXISTS get_active_dynamic_sort(uuid);
        DROP FUNCTION IF EXISTS apply_change_dynamic_sort_model();
        DROP FUNCTION IF EXISTS rebuild_dynamic_sort_model();
        """)
        drop_table_or_mv(self.db, "dynamic_sort_model")


# noinspection PyPep8Naming
class SearchRankWeightModelWithPrio_V1(ViewMigrationManager):
    """Manage the current search-rank-weight model."""

    uses = ()

    since = "create_effective_dated_search_rank_weights_20260831_003"

    def up(self) -> None:
        """Create the current search-rank-weight model and indexes."""
        create_effdted_model_view_with_prio_v4(self.db, "search_rank_weight")
        upsert_index_v1(self.db, "search_rank_weight_model", ["gid"], unique=True)
        upsert_index_v1(self.db, "search_rank_weight_model", ["entity_kind", "key"], unique=True)

    def down(self) -> None:
        """Drop the search-rank-weight model and its supporting objects."""
        self.db.executesql("""
        DROP TRIGGER IF EXISTS refresh_search_rank_weight_model_trigger ON search_rank_weight_ed;
        DROP TRIGGER IF EXISTS search_rank_weight_model_update_trigger ON search_rank_weight_ed;
        DROP FUNCTION IF EXISTS get_active_search_rank_weight(uuid);
        DROP FUNCTION IF EXISTS apply_change_search_rank_weight_model();
        DROP FUNCTION IF EXISTS rebuild_search_rank_weight_model();
        """)
        drop_table_or_mv(self.db, "search_rank_weight_model")
