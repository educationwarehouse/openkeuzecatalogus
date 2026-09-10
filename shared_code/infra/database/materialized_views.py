"""Materialized-view maintenance helpers."""

import psycopg2.errors

from shared_code.infra.database import advisory_semaphore_context
from shared_code.infra.database.context import DatabaseContext

DeadlockDetected: type[Exception] = psycopg2.errors.DeadlockDetected  # ty: ignore[unresolved-attribute]


def _refresh_all_materialized_views(db: DatabaseContext) -> list[str]:
    """Refresh every materialized view, concurrently when PostgreSQL supports it."""
    rows = db.executesql(
        "SELECT mview, refresh, is_concurrent, is_populated FROM materialized_views;",
        colnames=["name", "refresh", "is_concurrent", "is_populated"],
    )
    db.commit()

    refreshed_views = []
    for row in rows:
        materialized_view = row["name"]
        concurrently = "CONCURRENTLY" if row["is_concurrent"] and row["is_populated"] else ""
        query = f"REFRESH MATERIALIZED VIEW {concurrently} {materialized_view};"

        print(query)
        try:
            db.executesql(query)
            db.commit()
            refreshed_views.append(materialized_view)
        except DeadlockDetected:
            print("NOT REFRESHED:", materialized_view)
            db.rollback()

    return refreshed_views


def refresh_all_materialized_views(db: DatabaseContext) -> list[str]:
    """Refresh materialized views while preventing another worker from overlapping."""
    with advisory_semaphore_context(db, semaphore="refresh_all_materialized_views"):
        return _refresh_all_materialized_views(db)
