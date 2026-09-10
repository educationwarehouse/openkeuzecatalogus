"""Data-model field-name groups."""

INTERNAL_FIELD_NAMES = frozenset(
    {
        "id",
        "gid",
        "last_saved_by",
        "effstatus",
        "effdt",
        "sync_gid",
        "prio",
        "created_at",
        "updated_at",
    }
)

JSON_IMPORT_EXCLUDED_FIELD_NAMES = INTERNAL_FIELD_NAMES - {"gid", "effdt", "effstatus"}
EFFECTIVEDATED_UPDATE_EXCLUDED_FIELD_NAMES = INTERNAL_FIELD_NAMES - {
    "gid",
    "effstatus",
    "created_at",
    "updated_at",
}
