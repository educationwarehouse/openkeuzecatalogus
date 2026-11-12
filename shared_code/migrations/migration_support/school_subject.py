"""Migration support manager for `school_subject_model`."""

import json
from pathlib import Path

from edwh_migrate import ViewMigrationManager
from pydal.helpers.methods import bar_encode
from typedal import TypeDAL

from .core import create_effdted_model_view_with_prio_v4, drop_table_or_mv, upsert_index_v1


def seed_school_subjects_2026_2027_v1(db: TypeDAL) -> None:
    """Insert the versioned subject list without replacing existing history."""
    source = Path("/data/seeding/school_subjects_2026_2027_v1.json")
    subjects = json.loads(source.read_text(encoding="utf-8"))

    for subject in subjects:
        db.executesql(
            """
            INSERT INTO school_subject_ed (gid, name, aliases, last_saved_by)
            SELECT %(gid)s, %(name)s, %(aliases)s, %(last_saved_by)s
            WHERE NOT EXISTS (
                SELECT 1 FROM school_subject_ed WHERE gid = %(gid)s
            );
            """,
            placeholders={
                "gid": subject["gid"],
                "name": subject["name"],
                "aliases": bar_encode(subject["aliases"]),
                "last_saved_by": "migration/seed_school_subjects_2026_2027_20261102_002",
            },
        )


# noinspection PyPep8Naming
class SchoolSubjectModelWithPrio_V1(ViewMigrationManager):
    """Manage the current school subjects derived from historical versions."""

    uses = ()

    since = "create_school_subject_ed_20261102_001"

    def up(self) -> None:
        """Create the current model, synchronization triggers and indexes."""
        create_effdted_model_view_with_prio_v4(self.db, "school_subject")
        upsert_index_v1(self.db, "school_subject_model", ["gid"], unique=True)
        upsert_index_v1(self.db, "school_subject_model", ["name"], unique=True)

    def down(self) -> None:
        """Drop model objects, allowing the initial source-table creation."""
        self.db.executesql("""
            DROP TRIGGER IF EXISTS refresh_school_subject_model_trigger ON school_subject_ed;
            DROP TRIGGER IF EXISTS school_subject_model_update_trigger ON school_subject_ed;
            DROP FUNCTION IF EXISTS get_active_school_subject(uuid);
            DROP FUNCTION IF EXISTS apply_change_school_subject_model();
            DROP FUNCTION IF EXISTS rebuild_school_subject_model();
        """)
        drop_table_or_mv(self.db, "school_subject_model")
