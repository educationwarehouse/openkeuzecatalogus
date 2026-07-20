"""Helpers to import seed data from remote or file-based JSON endpoints."""

import datetime as dt
import json
import os
import typing as t
from pathlib import Path

import requests
from pgskewer import migrations  # noqa F401 - importing exposes these migrations
from typedal import TypeDAL
from yayarl import URL

from shared_code.data_model import AnyDict
from shared_code.migrations.migration_support import simple_progress


def insert_relationship_v1(
    db: TypeDAL,
    subject_gid: str,
    predicate: str,
    object_gid: str,
    seen_triples: set[tuple[str, str, str]],
    *,
    last_saved_by: str = "insert_relationship_v1",
    comment: str = "",
    check: bool = True,
) -> bool:
    """Insert one tagged relationship while avoiding duplicate triples."""
    triple = (subject_gid, predicate, object_gid)

    if triple in seen_triples:
        return False

    seen_triples.add(triple)

    if check:
        existing = db.executesql(
            """
            SELECT COUNT(*)
                FROM tagged_model
                WHERE subject_gid = %(subject_gid)s
                  AND predicate = %(predicate)s
                  AND object_gid = %(object_gid)s
            """,
            placeholders={
                "subject_gid": subject_gid,
                "predicate": predicate,
                "object_gid": object_gid,
            },
            colnames=("cnt",),
        )
        if existing[0]["cnt"]:
            return False

    db.executesql(
        """
        INSERT INTO tagged_ed (
                        gid,
                        subject_gid,
                        predicate,
                        object_gid,
                        effdt,
                        effstatus,
                        last_saved_by,
                        comment,
                        sync_gid
            )
            VALUES (
                        uuidv4(),
                        %(subject_gid)s,
                        %(predicate)s,
                        %(object_gid)s,
                        %(effdt)s,
                        %(effstatus)s,
                        %(last_saved_by)s,
                        %(comment)s,
                        uuidv7()
            )
        """,
        placeholders={
            "subject_gid": subject_gid,
            "predicate": predicate,
            "object_gid": object_gid,
            "last_saved_by": last_saved_by,
            "comment": comment or f"insert_relationship_v1.{predicate}",
            "effstatus": True,
            "effdt": dt.datetime.now(),
        },
    )
    return True


def fetch_seed_table_rows_v1(
    base_url: str,
    table_name: str,
    session: requests.Session | None = None,
    extra_headers: dict[str, str] | None = None,
    timeout: int = 60,
) -> list[AnyDict]:
    """Fetch seed rows for one table from HTTP or a file-backed JSON source."""
    base = URL(base_url)
    token = os.getenv("MIGRATE_SEED_BEARER_TOKEN", "")

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

    return payload


def import_seed_table_v1(
    db: TypeDAL,
    base_url: str,
    table_name: str,
    session: requests.Session | None = None,
    skip_columns: t.Iterable[str] = ("id",),
    timeout: int = 60,
    extra_headers: dict[str, str] | None = None,
) -> int:
    """Fetch one table's seed JSON and import via sync-gid upsert or naive insert based on payload."""
    payload = fetch_seed_table_rows_v1(
        base_url,
        table_name,
        session=session,
        extra_headers=extra_headers,
        timeout=timeout,
    )

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
        """  # noqa S608: all parameters are in our control so no SQL injection possible
    else:
        placeholders = ", ".join(f"%({col})s" for col in insertable_columns)
        columns_sql = ", ".join(insertable_columns)
        query = f"""
        INSERT INTO {table_name} ({columns_sql})
        VALUES ({placeholders})
        """  # noqa S608: all parameters are in our control so no SQL injection possible

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


def import_seed_relationships_v1(
    db: TypeDAL,
    base_url: str,
    table_name: str = "organisation_relations",
    session: requests.Session | None = None,
    timeout: int = 60,
    extra_headers: dict[str, str] | None = None,
    last_saved_by: str = "seed.organisation_relations",
) -> int:
    """Fetch relationship seed rows and import tagged relations."""
    payload = fetch_seed_table_rows_v1(
        base_url,
        table_name,
        session=session,
        extra_headers=extra_headers,
        timeout=timeout,
    )

    if not payload:
        return 0

    seen_triples: set[tuple[str, str, str]] = set()
    inserted = 0

    for row in simple_progress(payload):
        subject_gid = str(row["subject_gid"])
        predicate = str(row["predicate"])
        object_gid = str(row["object_gid"])

        if insert_relationship_v1(
            db,
            subject_gid,
            predicate,
            object_gid,
            seen_triples,
            last_saved_by=last_saved_by,
            comment=str(row.get("comment") or ""),
        ):
            inserted += 1

    return inserted
