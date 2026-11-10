"""Durable importer-run recording helpers."""

import dataclasses as dc
import datetime as dt

from typedal import TypeDAL

from shared_code.data_model import AnyDict
from shared_code.data_model.tables import (
    ImporterRun,
    ImporterRunEvent,
    Method,
    Product,
    Supplier,
)
from shared_code.modules.scrapers.types import ImportRunCountStat, ImportRunWarningStat, ImportStats
from shared_code.modules.scrapers.warnings import warning_details

DEFAULT_RUN_RETENTION = 20


def reconcile_failed_importer_runs(db: TypeDAL) -> int:
    """Finish interrupted import reports using their persisted queue failure results."""
    runs = db.executesql(
        """
        UPDATE importer_run AS run
        SET phase = 'failed', success = FALSE, finished_at = utcnow(),
            failure_message = 'Background job failed before import completion',
            duration_ms = GREATEST(0, EXTRACT(EPOCH FROM (utcnow() - run.started_at)) * 1000)::integer
        WHERE run.finished_at IS NULL
          AND EXISTS (
            SELECT 1 FROM pgqueuer_result AS result
            WHERE result.unique_key::text = run.job_key AND result.ok = FALSE
          )
        RETURNING run.gid;
        """,
    )
    return len(runs)


def record_importer_run(
    db: TypeDAL,
    source: str,
    endpoint_type: str | None,
    supplier_gid: str | None,
    supplier_name: str | None,
    job_key: str | None,
    started_at: dt.datetime,
    finished_at: dt.datetime,
    success: bool,
    payload_json: AnyDict,
    stats: ImportStats | None = None,
    failure_message: str | None = None,
    warnings: list[ImportRunWarningStat] | None = None,
    retention_limit: int = DEFAULT_RUN_RETENTION,
    run_gid: str | None = None,
    prune_aggregate_runs: bool = False,
) -> str:
    """Persist the final outcome and reporting facts for one importer run."""
    if run_gid:
        run = ImporterRun.where(ImporterRun.gid == run_gid).first()
        if not run:
            raise ValueError(f"Importer run {run_gid} does not exist")
        run.update_record(
            finished_at=finished_at,
            duration_ms=max(0, int((finished_at - started_at).total_seconds() * 1000)),
            success=success,
            phase="completed" if success else "failed",
            failure_message=failure_message,
            payload_json=payload_json,
        )
    else:
        run_gid = ImporterRun.insert(
            source=source,
            endpoint_type=endpoint_type,
            supplier_gid=supplier_gid,
            supplier_name=supplier_name,
            job_key=job_key,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=max(0, int((finished_at - started_at).total_seconds() * 1000)),
            success=success,
            phase="completed" if success else "failed",
            failure_message=failure_message,
            payload_json=payload_json,
        ).gid

    # Finalization replaces the warning snapshot, including when a post-run hook fails.
    ImporterRunEvent.where(run_gid=run_gid, event_type="warning").delete()
    for warning in warnings or []:
        ImporterRunEvent.insert(
            run_gid=run_gid,
            supplier_gid=warning.supplier_gid or supplier_gid,
            supplier_name=warning.supplier_name or supplier_name,
            event_type="warning",
            metric=warning.warning_code.value,
            entity_type=warning.entity_type,
            entity_gid=warning.entity_gid,
            entity_olid=warning.entity_olid,
            entity_name=warning.product_name[:255] if warning.product_name else None,
            details=dict(warning_details(warning)),
        )

    if stats is not None:
        for count_stat in _derive_count_stats(stats=stats, supplier_gid=supplier_gid, supplier_name=supplier_name):
            ImporterRunEvent.insert(
                run_gid=run_gid,
                supplier_gid=count_stat.supplier_gid,
                supplier_name=count_stat.supplier_name,
                event_type="metric",
                scope_type=count_stat.count_type,
                scope_key=count_stat.count_key,
                scope_label=count_stat.count_label,
                metric=count_stat.metric,
                entity_type="metric",
                value=count_stat.value,
            )

        for error_stat in stats.error_stats:
            ImporterRunEvent.insert(
                run_gid=run_gid,
                supplier_gid=error_stat.supplier_gid,
                supplier_name=error_stat.supplier_name,
                event_type="error",
                metric=error_stat.error_code,
                entity_type=error_stat.entity_type,
                entity_gid=error_stat.entity_gid,
                entity_olid=error_stat.entity_olid,
                entity_name=error_stat.entity_name,
                details={
                    "method_gid": error_stat.method_gid,
                    "method_name": error_stat.method_name,
                    "validation_failed": error_stat.validation_failed,
                    "error_details": error_stat.error_details,
                },
            )

        for outcome in stats.entity_outcomes:
            ImporterRunEvent.insert(
                run_gid=run_gid,
                supplier_gid=outcome.supplier_gid,
                event_type="entity",
                metric=outcome.outcome,
                entity_type=outcome.entity_type,
                entity_gid=outcome.entity_gid,
                entity_olid=outcome.entity_olid,
                entity_name=outcome.entity_name,
            )

    _prune_old_runs(
        db,
        supplier_gid,
        keep_last=retention_limit,
        source=source,
        prune_aggregate_runs=prune_aggregate_runs,
    )
    db.commit()
    return run_gid


def start_importer_run(
    db: TypeDAL,
    *,
    source: str,
    endpoint_type: str | None,
    supplier_gid: str | None,
    supplier_name: str | None,
    job_key: str | None,
    started_at: dt.datetime,
) -> str:
    """Create the parent row needed for live importer progress events."""
    run_gid = ImporterRun.insert(
        source=source,
        endpoint_type=endpoint_type,
        supplier_gid=supplier_gid,
        supplier_name=supplier_name,
        job_key=job_key,
        started_at=started_at,
        phase="importing",
        payload_json={},
    ).gid
    db.commit()
    return run_gid


def resolve_supplier_name(supplier_gid: str | None) -> str | None:
    """Resolve a supplier name for one supplier gid."""
    if not supplier_gid:
        return None
    supplier = Supplier.where(Supplier.gid == supplier_gid).select(Supplier.name).first()
    return supplier.name if supplier else None


def _derive_count_stats(
    stats: ImportStats,
    supplier_gid: str | None,
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
    for supplier_gid, supplier_stats in stats.supplier_type_stats.items():
        resolved_name = resolve_supplier_name(supplier_gid)
        for entity_type, type_stats in (("method", supplier_stats.methods), ("product", supplier_stats.products)):
            count_stats.extend(
                ImportRunCountStat(
                    count_type="supplier_change",
                    count_key=f"{supplier_gid}:{entity_type}",
                    count_label=resolved_name or supplier_gid,
                    metric=field.name,
                    value=int(getattr(type_stats, field.name)),
                    supplier_gid=supplier_gid,
                    supplier_name=resolved_name,
                )
                for field in dc.fields(type_stats)
            )
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
    supplier_gid: str | None,
    supplier_name: str | None,
) -> list[ImportRunCountStat]:
    """Capture current method/product counts for the imported supplier."""
    query = Product.supplier_gid == supplier_gid if supplier_gid else None
    products = Product.where(query).count() if query is not None else Product.count()
    methods = Method.where(Method.supplier_gid == supplier_gid).count() if supplier_gid else Method.count()
    count_key = supplier_gid or "all-suppliers"

    stats = [
        ImportRunCountStat(
            count_type="supplier",
            count_key=count_key,
            count_label=supplier_name or "Alle leveranciers",
            metric="product_count",
            value=int(products),
            supplier_gid=supplier_gid,
            supplier_name=supplier_name,
        ),
        ImportRunCountStat(
            count_type="supplier",
            count_key=count_key,
            count_label=supplier_name or "Alle leveranciers",
            metric="method_count",
            value=int(methods),
            supplier_gid=supplier_gid,
            supplier_name=supplier_name,
        ),
    ]

    method_query = Method.supplier_gid == supplier_gid if supplier_gid else Method.id > 0
    method_rows = Method.where(method_query).select(Method.gid, Method.name, Method.supplier_gid)
    product_counts = _count_products_by_method([method.gid for method in method_rows])
    for method in method_rows:
        product_count = product_counts.get(method.gid, 0)
        method_supplier_gid = method.supplier_gid if method.supplier_gid else supplier_gid
        stats.append(
            ImportRunCountStat(
                count_type="method",
                count_key=method.gid,
                count_label=str(method.name or method.gid),
                metric="product_count",
                value=int(product_count),
                supplier_gid=method_supplier_gid,
                supplier_name=supplier_name,
            )
        )

    return stats


def _prune_old_runs(
    db: TypeDAL,
    supplier_gid: str | None,
    keep_last: int,
    source: str = "",
    prune_aggregate_runs: bool = False,
) -> None:
    """Keep the newest N supplier runs, optionally pruning aggregate runs per source."""
    if keep_last <= 0:
        return

    if not supplier_gid and not prune_aggregate_runs:
        return

    db.executesql(
        t"""
        WITH rows_to_delete AS (
          SELECT id
          FROM importer_run
          WHERE supplier_gid IS NOT DISTINCT FROM {supplier_gid}
            AND ({bool(supplier_gid)} OR {source = })
            AND finished_at IS NOT NULL
          ORDER BY finished_at DESC, id DESC
          OFFSET {keep_last}
        )
        DELETE FROM importer_run
        WHERE id IN (
          SELECT id
          FROM rows_to_delete
        )
        """,
    )
