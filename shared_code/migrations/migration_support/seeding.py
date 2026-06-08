"""Helpers to import seed data from remote or file-based JSON endpoints."""

import json
import os
import typing as t
from pathlib import Path

import requests
from pgskewer import migrations  # noqa F401 - importing exposes these migrations
from typedal import TypeDAL
from yarl import URL


def import_seed_table_v1(
    db: TypeDAL,
    base_url: str,
    table_name: str,
    bearer_token: str | None = None,
    session: requests.Session | None = None,
    skip_columns: t.Iterable[str] = ("id",),
    timeout: int = 60,
    extra_headers: dict[str, str] | None = None,
) -> int:
    """Fetch one table's seed JSON and import via sync-gid upsert or naive insert based on payload."""
    token = bearer_token or os.getenv("MIGRATE_SEED_BEARER_TOKEN", "")

    base = URL(base_url)

    if base.scheme == "file":
        endpoint_url = str(base / table_name).removeprefix("file://") + ".json"
        payload = json.loads(Path(endpoint_url).read_text())
    else:
        endpoint_url = base / "seed" / table_name

        response = (session or requests).get(
            str(endpoint_url),
            headers={"Authorization": f"Bearer {token}"} | (extra_headers or {}),
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()

    if not isinstance(payload, list):
        raise ValueError(f"Seed endpoint did not return a list: {endpoint_url}")
    if not all(isinstance(row, dict) for row in payload):
        raise ValueError(f"Seed endpoint contains non-object rows: {endpoint_url}")

    table_columns = db.executesql(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %(table_name)s
        """,
        placeholders={"table_name": table_name},
        as_dict=True,
    )
    column_types = {col["column_name"]: col["data_type"] for col in table_columns}
    known_columns = set(column_types) - set(skip_columns)

    if not payload:
        return 0

    first_row = payload[0]

    insertable_columns = [col for col in first_row if col in known_columns]

    if "sync_gid" in insertable_columns:
        placeholders = ", ".join(f"%({col})s" for col in insertable_columns)
        columns_sql = ", ".join(insertable_columns)
        update_columns = [col for col in insertable_columns if col != "sync_gid"]
        update_sql = ", ".join(f"{col} = EXCLUDED.{col}" for col in update_columns)
        query = f"""
        INSERT INTO {table_name} ({columns_sql})
        VALUES ({placeholders})
        ON CONFLICT (sync_gid) DO UPDATE
        SET {update_sql}
        """
    else:
        placeholders = ", ".join(f"%({col})s" for col in insertable_columns)
        columns_sql = ", ".join(insertable_columns)
        query = f"""
        INSERT INTO {table_name} ({columns_sql})
        VALUES ({placeholders})
        """

    def prepare_placeholders(row: dict[str, t.Any]) -> dict[str, t.Any]:
        placeholders_map = {}
        for col in insertable_columns:
            value = row.get(col)
            data_type = column_types.get(col)

            if data_type in ("json", "jsonb") and value is not None:
                value = json.dumps(value)

            placeholders_map[col] = value

        return placeholders_map

    for row in payload:
        try:
            placeholders = prepare_placeholders(row)

            db.executesql(query, placeholders=placeholders)
        except Exception as e:
            print("failed on", row)
            db.rollback()
            raise e

    return len(payload)
