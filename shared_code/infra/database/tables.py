"""Database table metadata helpers."""

from typedal import TypeDAL


def is_readonly_table(db: TypeDAL, table_name: str) -> bool:
    """Return whether a table is rebuilt or refreshed by a database function."""
    if table_name.endswith("_model"):
        return True

    table_model = f"{table_name}_model"
    rows = db.executesql(
        """
        SELECT 1
        FROM pg_proc function
        JOIN pg_namespace namespace ON namespace.oid = function.pronamespace
        WHERE namespace.nspname = 'public'
          AND function.proname IN (
              %(rebuild)s,
              %(rebuild_model)s,
              %(refresh)s,
              %(refresh_model)s
          )
        LIMIT 1
        """,
        placeholders={
            "rebuild": f"rebuild_{table_name}",
            "rebuild_model": f"rebuild_{table_model}",
            "refresh": f"refresh_{table_name}",
            "refresh_model": f"refresh_{table_model}",
        },
    )
    return bool(rows)
