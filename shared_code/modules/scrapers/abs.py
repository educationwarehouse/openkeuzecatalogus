"""Abstract importer contract used by scraper integrations."""

import abc
import datetime as dt
import traceback
import typing as t

from endow import Service

from shared_code.data_model import Product
from shared_code.infra.database import DatabaseContext, database_context, rebuild_model
from shared_code.infra.database.bulk_operations import bulk_operation_context
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.scrapers.errors import ImportWarningCode
from shared_code.modules.scrapers.flow import ImportFlow
from shared_code.modules.scrapers.run_log import record_importer_run, resolve_supplier_name, start_importer_run
from shared_code.modules.scrapers.types import (
    CdnImageUploadStats,
    ImportMethod,
    ImportPriority,
    ImportProduct,
    ImportRunWarningStat,
    ImportStats,
    ImportSupplier,
    ImportVision,
)
from shared_code.services import Applogger, ImageStorage
from shared_code.services.images import ImageStorageError


class ImportRunExtras(t.TypedDict, total=False):
    """Optional arguments accepted when launching an import run."""

    base_url: str
    endpoint_publisher: str | None
    endpoint_uses_pagination: bool
    supplier_gid: str | None
    endpoint_type: str | None
    job_key: str | None
    trigger: str | None


class AbstractImporter(Service, abc.ABC):
    """Source-agnostic importer contract.

    Importers should return standardized dictionaries that match `MethodEd` and
    `ProductEd` payload field names, minus effectivedated meta fields.
    """

    db: DatabaseContext
    applog: Applogger
    image_storage: ImageStorage
    flow: ImportFlow

    source = "unknown-importer"
    prune_aggregate_runs = False
    priority: ImportPriority = ImportPriority.IMPORTER_OK
    mark_removed: bool = True
    last_saved_by: str | None = None
    supplier_gid: str | None = None
    run_gid: str | None = None
    removed_supplier_gids: set[str] | None = None

    def __init__(self, **_: t.Any) -> None:
        """Ignore constructor extras that individual importers may accept."""
        super().__init__()
        self._warnings: list[ImportRunWarningStat] = []

    @abc.abstractmethod
    def fetch_methods(self) -> list[ImportMethod]:
        """Fetch and normalize methods into the shared structure."""
        raise NotImplementedError

    @abc.abstractmethod
    def fetch_products(self) -> list[ImportProduct]:
        """Fetch and normalize products into the shared structure."""
        raise NotImplementedError

    def fetch_suppliers(self) -> list[ImportSupplier]:
        """Return optional supplier payloads for importers that provide them."""
        return []

    def fetch_visions(self) -> list[ImportVision]:
        """Return optional vision payloads for importers that provide them."""
        return []

    def before_import(self) -> None:
        """Run before any import step."""
        return None

    def after_methods_and_products_import(self, stats: ImportStats) -> None:
        """Run after methods and products import."""
        return None

    def after_import(self, stats: ImportStats) -> None:
        """Run after all import steps."""
        return None

    def after_run_logged(self, run_gid: str, stats: ImportStats | None) -> None:
        """Persist importer-specific reporting facts after the generic run record exists."""
        return None

    def import_suppliers(self) -> ImportStats:
        """Import supplier rows and persist their run stats."""
        stats = ImportStats()
        suppliers = self.fetch_suppliers()
        if not suppliers:
            return stats
        supplier_stats = self.flow.upsert_suppliers(
            suppliers=suppliers,
            prio=self.priority,
            last_saved_by=self.last_saved_by or self.source,
        )
        self.db.commit()
        stats.suppliers = supplier_stats
        return stats

    def import_methods_and_products(
        self,
        *,
        prio: int | ImportPriority,
        last_saved_by: str,
        mark_removed: bool = True,
    ) -> ImportStats:
        """Import methods and products with shared flow helpers."""
        return self.flow.import_methods_and_products(
            methods=self.fetch_methods(),
            products=self.fetch_products(),
            prio=prio,
            last_saved_by=last_saved_by,
            mark_removed=mark_removed,
            removed_supplier_gid=self.supplier_gid,
            removed_supplier_gids=self.removed_supplier_gids,
        )

    def import_visions(self) -> ImportStats:
        """Import vision rows and persist their run stats."""
        stats = ImportStats()
        visions = self.fetch_visions()
        if not visions:
            return stats
        vision_stats = self.flow.upsert_visions(
            visions=visions,
            prio=self.priority,
            last_saved_by=self.last_saved_by or self.source,
        )
        self.db.commit()
        stats.visions = vision_stats
        return stats

    def sync_images_to_cdn(self) -> CdnImageUploadStats:
        """Store imported product images and persist their resulting public URLs."""
        stats = CdnImageUploadStats()
        if not self.supplier_gid:
            return stats

        products = Product.where(Product.supplier_gid == self.supplier_gid).select(
            Product.gid,
            Product.olid,
            Product.isbn,
            Product.name,
            Product.image_url,
        )
        updated_images = False

        for product in products:
            if not product.gid or not product.image_url:
                stats.skipped += 1
                continue

            if self.image_storage.is_file_url(product.image_url):
                stats.skipped += 1
                continue

            try:
                stats.attempted += 1
                upload_key = product.isbn or product.gid
                _, image_url = self.image_storage.upload_from_url(upload_key, product.image_url)
            except ImageStorageError as error:
                stats.failed += 1
                self._warn_import(
                    warning_code=ImportWarningCode.IMAGE_UPLOAD_FAILED,
                    message=f"Could not store image for product {product.gid}: {error}",
                    product_name=product.name,
                    reason=str(error),
                    source_url=product.image_url,
                    entity_type="product",
                    entity_gid=product.gid,
                    entity_olid=product.olid,
                )
                continue

            stats.uploaded += 1

            self.flow.insert_into_effdt_if_changed_for_prio(
                Product,
                product.gid,
                {"image_url": image_url},
                prio=self.priority,
                last_saved_by=self.last_saved_by or self.source,
            )
            updated_images = True

        if updated_images:
            rebuild_model(self.db, "product")
            self.db.commit()

        return stats

    def import_into_db(
        self,
        prio: int | ImportPriority | None = None,
        last_saved_by: str | None = None,
        mark_removed: bool | None = None,
    ) -> ImportStats:
        """Run lifecycle stages; production callers enter via locked try_import_into_db()."""
        resolved_prio = ImportPriority.normalize(prio if prio is not None else self.priority)
        resolved_last_saved_by = last_saved_by or self.last_saved_by or self.source
        resolved_mark_removed = self.mark_removed if mark_removed is None else mark_removed

        self.before_import()
        supplier_stats = self.import_suppliers()
        stats = self.import_methods_and_products(
            prio=resolved_prio,
            last_saved_by=resolved_last_saved_by,
            mark_removed=resolved_mark_removed,
        )
        stats.suppliers = supplier_stats.suppliers
        self.after_methods_and_products_import(stats)
        vision_stats = self.import_visions()

        stats.image_uploads = self.sync_images_to_cdn()

        stats.visions = vision_stats.visions
        self.after_import(stats)
        stats.warning_stats.extend(self._warnings)
        return stats

    def _warn_import(
        self,
        warning_code: ImportWarningCode,
        message: str,
        product_name: str | None = None,
        reason: str | None = None,
        source_url: str | None = None,
        supplier_gid: str | None = None,
        supplier_name: str | None = None,
        entity_type: t.Literal["run", "supplier", "method", "product"] | None = None,
        entity_gid: str | None = None,
        entity_olid: str | None = None,
    ) -> None:
        if entity_type is None:
            entity_type = "product" if product_name else "run"
        warning = ImportRunWarningStat(
            warning_code=warning_code,
            message=message,
            product_name=product_name,
            reason=reason,
            source_url=source_url,
            supplier_gid=supplier_gid or self.supplier_gid,
            supplier_name=supplier_name,
            entity_type=entity_type,
            entity_gid=entity_gid,
            entity_olid=entity_olid,
        )
        if warning not in self._warnings:
            self._warnings.append(warning)

    def _log_import_event(
        self,
        action: str,
        supplier_gid: str | None,
        endpoint_type: str | None,
        job_key: str | None,
        started_at: dt.datetime,
        success: bool | None = None,
        failure_message: str | None = None,
    ) -> None:
        details: dict[str, str | bool | None] = {
            "source": self.source,
            "supplier_gid": supplier_gid,
            "endpoint_type": endpoint_type,
            "job_key": job_key,
            "started_at": started_at.isoformat(),
        }
        if success is not None:
            details["success"] = success
        if failure_message is not None:
            details["failure_message"] = failure_message
        self.applog.try_fire(
            {
                "kind": "event" if success is not False else "error",
                "action": action,
                "related": supplier_gid,
                "details": details,
            }
        )

    def try_import_into_db(
        self,
        prio: int | ImportPriority | None = None,
        last_saved_by: str | None = None,
        mark_removed: bool | None = None,
        **extras: t.Unpack[ImportRunExtras],
    ) -> ImportStats:
        """Serialize the complete import, including image updates and reporting."""
        # All runtime model rebuilds belong to this lifecycle. Lock before even
        # reading supplier data, not only at rebuild_model() after taking locks.
        with bulk_operation_context(self.db):
            return self._try_import_into_db(
                prio=prio,
                last_saved_by=last_saved_by,
                mark_removed=mark_removed,
                **extras,
            )

    def _try_import_into_db(
        self,
        prio: int | ImportPriority | None = None,
        last_saved_by: str | None = None,
        mark_removed: bool | None = None,
        **extras: t.Unpack[ImportRunExtras],
    ) -> ImportStats:
        """Run the import flow and persist a durable finished-run record."""
        started_at = dt.datetime.now()

        supplier_gid = extras.get("supplier_gid")
        endpoint_type = extras.get("endpoint_type")
        job_key = extras.get("job_key")

        supplier_name = resolve_supplier_name(supplier_gid)
        self.run_gid = start_importer_run(
            self.db,
            source=self.source,
            endpoint_type=endpoint_type,
            supplier_gid=supplier_gid,
            supplier_name=supplier_name,
            job_key=job_key,
            started_at=started_at,
        )

        self._log_import_event(
            action="scraper-import-started",
            supplier_gid=supplier_gid,
            endpoint_type=endpoint_type,
            job_key=job_key,
            started_at=started_at,
        )

        stats: ImportStats | None = None
        try:
            stats = self.import_into_db(
                prio=prio,
                last_saved_by=last_saved_by,
                mark_removed=mark_removed,
            )
            run_gid = record_importer_run(
                self.db,
                source=self.source,
                endpoint_type=endpoint_type,
                supplier_gid=supplier_gid,
                supplier_name=supplier_name,
                job_key=job_key,
                started_at=started_at,
                finished_at=dt.datetime.now(),
                success=True,
                payload_json=dict(extras),
                stats=stats,
                warnings=stats.warning_stats,
                run_gid=self.run_gid,
                prune_aggregate_runs=self.prune_aggregate_runs,
            )
            self.after_run_logged(run_gid, stats)
            self._log_import_event(
                action="scraper-import-finished",
                supplier_gid=supplier_gid,
                endpoint_type=endpoint_type,
                job_key=job_key,
                started_at=started_at,
                success=True,
            )
            return stats
        except Exception as exc_outer:
            failure_message = "".join(traceback.format_exception_only(type(exc_outer), exc_outer)).strip()
            self._log_import_event(
                action="scraper-import-failed",
                supplier_gid=supplier_gid,
                endpoint_type=endpoint_type,
                job_key=job_key,
                started_at=started_at,
                success=False,
                failure_message=failure_message,
            )
            self.db.rollback()
            try:
                run_gid = record_importer_run(
                    self.db,
                    source=self.source,
                    endpoint_type=endpoint_type,
                    supplier_gid=supplier_gid,
                    supplier_name=supplier_name,
                    job_key=job_key,
                    started_at=started_at,
                    finished_at=dt.datetime.now(),
                    success=False,
                    payload_json=dict(extras),
                    failure_message=failure_message,
                    warnings=stats.warning_stats if stats is not None else self._warnings,
                    run_gid=self.run_gid,
                    prune_aggregate_runs=self.prune_aggregate_runs,
                )
                self.after_run_logged(run_gid, None)
            except Exception:
                self.db.rollback()

            raise exc_outer

    @classmethod
    def run(cls, **extras: t.Unpack[ImportRunExtras]) -> ImportStats:
        """Launch the importer in its configured database context."""
        with database_context(cls.source) as db:
            importer = cls.with_injected(
                db=db,
                auth_adapter=AuthAdapter.for_service(cls.source),
                **extras,
            )
            return importer.try_import_into_db(**extras)
