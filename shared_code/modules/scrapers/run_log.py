"""Durable importer-run recording helpers."""

import dataclasses as dc
import datetime as dt
import typing as t

from typedal import TypeDAL

from shared_code.data_model.tables import (
    ImporterRun,
    ImporterRunCountStat,
    ImporterRunErrorStat,
    Method,
    Product,
    Supplier,
)
from shared_code.modules.scrapers.types import ImportRunCountStat, ImportRunWarningStat, ImportStats

DEFAULT_RUN_RETENTION = 20


def record_importer_run(
    db: TypeDAL,
    source: str,
    endpoint_type: str | None,
    supplier_gid: str,
    supplier_name: str | None,
    job_key: str | None,
    started_at: dt.datetime,
    finished_at: dt.datetime,
    success: bool,
    payload_json: dict[str, t.Any],
    stats: ImportStats | None = None,
    failure_message: str | None = None,
    warnings: list[ImportRunWarningStat] | None = None,
    retention_limit: int = DEFAULT_RUN_RETENTION,
) -> str:
    """Persist one finished importer run and its reporting facts."""
    run_gid = str(
        ImporterRun.insert(
            source=source,
            endpoint_type=endpoint_type,
            supplier_gid=supplier_gid,
            supplier_name=supplier_name,
            job_key=job_key,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=max(0, int((finished_at - started_at).total_seconds() * 1000)),
            success=success,
            failure_message=failure_message,
            payload_json=payload_json,
            warnings_json=[dc.asdict(warning) for warning in (warnings or [])],
        ).gid
    )

    if stats is not None:
        for count_stat in _derive_count_stats(stats=stats, supplier_gid=supplier_gid, supplier_name=supplier_name):
            ImporterRunCountStat.insert(run_gid=run_gid, **dc.asdict(count_stat))

        for error_stat in stats.error_stats:
            ImporterRunErrorStat.insert(run_gid=run_gid, **dc.asdict(error_stat))

    _prune_old_runs(db, supplier_gid, keep_last=retention_limit)
    db.commit()
    return run_gid


def resolve_supplier_name(supplier_gid: str | None) -> str | None:
    """Resolve a supplier name for one supplier gid."""
    if not supplier_gid:
        return None
    supplier = Supplier.where(Supplier.gid == supplier_gid).select(Supplier.name).first()
    return str(supplier.name) if supplier and supplier.name else None


def _derive_count_stats(
    stats: ImportStats,
    supplier_gid: str,
    supplier_name: str | None,
) -> list[ImportRunCountStat]:
    """Combine in-memory totals with current model snapshots for reporting."""
    count_stats = list(stats.count_stats)

    count_stats.extend(
        [
            ImportRunCountStat(
                count_type="run",
                count_key="supplier",
                count_label="Leverancier",
                metric="imported",
                value=stats.suppliers.imported,
                supplier_gid=supplier_gid,
                supplier_name=supplier_name,
            ),
            ImportRunCountStat(
                count_type="run",
                count_key="vision",
                count_label="Visie",
                metric="imported",
                value=stats.visions.imported,
                supplier_gid=supplier_gid,
                supplier_name=supplier_name,
            ),
        ]
    )

    count_stats.extend(
        [
            ImportRunCountStat(
                count_type="run",
                count_key="image_upload",
                count_label="CDN-afbeeldingen",
                metric=metric,
                value=value,
                supplier_gid=supplier_gid,
                supplier_name=supplier_name,
            )
            for metric, value in dc.asdict(stats.image_uploads).items()
        ]
    )

    count_stats.extend(_snapshot_supplier_method_counts(supplier_gid=supplier_gid, supplier_name=supplier_name))
    return count_stats


def _count_products_by_method(method_gids: list[str]) -> dict[str, int]:
    """Count products per method in one grouped query instead of one query per method."""
    if not method_gids:
        return {}

    method_gid_field = Product.method_gid
    count_field = Product.id.count()
    rows = (
        Product.where(method_gid_field.belongs(method_gids))
        .select(method_gid_field, count_field, groupby=method_gid_field)
        .execute()
    )
    # Methods without products are absent here; callers fall back to 0.
    return {str(row[method_gid_field]): int(row[count_field]) for row in rows}


def _snapshot_supplier_method_counts(
    supplier_gid: str,
    supplier_name: str | None,
) -> list[ImportRunCountStat]:
    """Capture current method/product counts for the imported supplier."""
    query = Product.supplier_gid == supplier_gid if supplier_gid else None
    products = Product.where(query).count() if query is not None else Product.count()
    methods = Method.where(Method.supplier_gid == supplier_gid).count() if supplier_gid else Method.count()

    stats = [
        ImportRunCountStat(
            count_type="supplier",
            count_key=supplier_gid,
            count_label=supplier_name or "Alle leveranciers",
            metric="product_count",
            value=int(products),
            supplier_gid=supplier_gid,
            supplier_name=supplier_name,
        ),
        ImportRunCountStat(
            count_type="supplier",
            count_key=supplier_gid,
            count_label=supplier_name or "Alle leveranciers",
            metric="method_count",
            value=int(methods),
            supplier_gid=supplier_gid,
            supplier_name=supplier_name,
        ),
    ]

    method_query = Method.supplier_gid == supplier_gid
    method_rows = Method.where(method_query).select(Method.gid, Method.name, Method.supplier_gid)
    product_counts = _count_products_by_method([str(method.gid) for method in method_rows])
    for method in method_rows:
        product_count = product_counts.get(str(method.gid), 0)
        method_supplier_gid = str(method.supplier_gid) if method.supplier_gid else supplier_gid
        stats.append(
            ImportRunCountStat(
                count_type="method",
                count_key=str(method.gid),
                count_label=str(method.name or method.gid),
                metric="product_count",
                value=int(product_count),
                supplier_gid=method_supplier_gid,
                supplier_name=supplier_name,
            )
        )

    return stats


def _prune_old_runs(db: TypeDAL, supplier_gid: str, keep_last: int) -> None:
    """Keep only the newest N runs for one source/supplier combination."""
    if keep_last <= 0:
        return

    if not supplier_gid:
        return
    db.executesql(
        t"""
        WITH rows_to_delete AS (
          SELECT id
          FROM importer_run
          WHERE {supplier_gid = }
          ORDER BY finished_at DESC, id DESC
          OFFSET {keep_last}
        )
        DELETE FROM importer_run
        WHERE id IN (
          SELECT id
          FROM rows_to_delete
        )
        """
    )
