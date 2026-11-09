"""Migration support manager for `decision_team_model`."""

from edwh_migrate import ViewMigrationManager

from .core import create_effdted_model_view_with_prio_v4, drop_table_or_mv, upsert_index_v1


class DecisionTeamModelWithPrio_V1(ViewMigrationManager):
    """Manage create/drop operations for the current decision-team model."""

    uses = ()

    since = "create_effective_dated_decision_teams_20260818_002"

    def up(self) -> None:
        """Create the current decision-team model and its indexes."""
        self.db.executesql("""
        ALTER TABLE decision_process DROP CONSTRAINT IF EXISTS decision_process_team_gid_fkey;
        """)
        create_effdted_model_view_with_prio_v4(self.db, "decision_team")
        upsert_index_v1(
            self.db,
            "decision_team_model",
            ["gid"],
            include=["location_gid", "name"],
            unique=True,
        )
        upsert_index_v1(
            self.db,
            "decision_team_model",
            ["location_gid", "name"],
            include=["gid"],
        )

    def down(self) -> None:
        """Drop the current decision-team model and its trigger functions."""
        self.db.executesql("""
        ALTER TABLE decision_process DROP CONSTRAINT IF EXISTS decision_process_team_gid_fkey;
        """)
        self.db.executesql("""
        DROP TRIGGER IF EXISTS refresh_decision_team_model_trigger ON decision_team_ed;
        DROP TRIGGER IF EXISTS decision_team_model_update_trigger ON decision_team_ed;
        """)
        self.db.executesql("""
        DROP FUNCTION IF EXISTS get_active_decision_team(uuid);
        DROP FUNCTION IF EXISTS apply_change_decision_team_model();
        DROP FUNCTION IF EXISTS rebuild_decision_team_model();
        """)
        drop_table_or_mv(self.db, "decision_team_model")
