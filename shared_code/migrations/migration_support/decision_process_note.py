"""Migration support manager for `decision_process_note_model`."""

from edwh_migrate import ViewMigrationManager

from .core import create_effdted_model_view_with_prio_v4, drop_table_or_mv, upsert_index_v1


# noinspection PyPep8Naming
class DecisionProcessNoteModelWithPrio_V1(ViewMigrationManager):
    """Manage create/drop operations for the current decision-process-note model."""

    uses = ()

    since = "create_effective_dated_decision_process_notes_20260818_003"

    def up(self) -> None:
        """Create the current decision-process-note model and its indexes."""
        create_effdted_model_view_with_prio_v4(self.db, "decision_process_note")
        upsert_index_v1(
            self.db,
            "decision_process_note_model",
            ["gid"],
            include=["organisation_gid", "theme"],
            unique=True,
        )
        upsert_index_v1(
            self.db,
            "decision_process_note_model",
            ["organisation_gid", "theme"],
            include=["gid", "content"],
        )

    def down(self) -> None:
        """Drop the current decision-process-note model and its trigger functions."""
        self.db.executesql("""
        DROP TRIGGER IF EXISTS refresh_decision_process_note_model_trigger ON decision_process_note_ed;
        DROP TRIGGER IF EXISTS decision_process_note_model_update_trigger ON decision_process_note_ed;
        """)
        self.db.executesql("""
        DROP FUNCTION IF EXISTS get_active_decision_process_note(uuid);
        DROP FUNCTION IF EXISTS apply_change_decision_process_note_model();
        DROP FUNCTION IF EXISTS rebuild_decision_process_note_model();
        """)
        drop_table_or_mv(self.db, "decision_process_note_model")
