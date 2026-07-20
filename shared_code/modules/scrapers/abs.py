"""Abstract importer contract used by scraper integrations."""

import abc
import datetime as dt
import traceback
import typing as t

from typedal import TypeDAL

from shared_code.infra.database import database_context
from shared_code.modules.scrapers.run_log import record_importer_run, resolve_supplier_name
from shared_code.modules.scrapers.types import (
    ImportMethod,
    ImportPriority,
    ImportProduct,
    ImportStats,
    ImportSupplier,
    ImportVision,
    JsonObject,
    JsonValue,
)
from shared_code.services import Applogger


class ImportRunExtras(t.TypedDict, total=False):
    """Optional arguments accepted when launching an import run."""

    base_url: str
    supplier_gid: str
    endpoint_type: str | None
    job_key: str | None
    sync_cdn: bool


class AbstractImporter(abc.ABC):
    """Source-agnostic importer contract.

    Importers should return standardized dictionaries that match `MethodEd` and
    `ProductEd` payload field names, minus effectivedated meta fields.
    """

    applog: Applogger

    def __init__(self, **_: t.Any) -> None:
        """Ignore constructor extras that individual importers may accept."""
        super().__init__()

    source = "unknown-importer"
    priority: ImportPriority = ImportPriority.IMPORTER_OK
    mark_removed: bool = True
    last_saved_by: str | None = None

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

    def before_import(self, db: TypeDAL) -> None:
        """Run before any import step."""
        return None

    def after_methods_and_products_import(self, db: TypeDAL, stats: ImportStats) -> None:
        """Run after methods and products import."""
        return None

    def after_import(self, db: TypeDAL, stats: ImportStats) -> None:
        """Run after all import steps."""
        return None

    def import_suppliers(self, db: TypeDAL) -> ImportStats:
        """Import supplier rows and persist their run stats."""
        from shared_code.modules.scrapers.flow import upsert_suppliers

        stats = ImportStats()
        suppliers = self.fetch_suppliers()
        if not suppliers:
            return stats
        supplier_stats = upsert_suppliers(
            db,
            suppliers=suppliers,
            prio=self.priority,
            last_saved_by=self.last_saved_by or self.source,
        )
        db.commit()
        stats.suppliers = supplier_stats
        return stats

    def import_methods_and_products(
        self,
        db: TypeDAL,
        *,
        prio: int | ImportPriority,
        last_saved_by: str,
        mark_removed: bool,
    ) -> ImportStats:
        """Import methods and products with shared flow helpers."""
        from shared_code.modules.scrapers.flow import import_methods_and_products

        return import_methods_and_products(
            db=db,
            methods=self.fetch_methods(),
            products=self.fetch_products(),
            prio=prio,
            last_saved_by=last_saved_by,
            mark_removed=mark_removed,
        )

    def import_visions(self, db: TypeDAL) -> ImportStats:
        """Import vision rows and persist their run stats."""
        from shared_code.modules.scrapers.flow import upsert_visions

        stats = ImportStats()
        visions = self.fetch_visions()
        if not visions:
            return stats
        vision_stats = upsert_visions(
            db,
            visions=visions,
            prio=self.priority,
            last_saved_by=self.last_saved_by or self.source,
        )
        db.commit()
        stats.visions = vision_stats
        return stats

    def sync_images_to_cdn(self, db: TypeDAL) -> None:
        """Synchronize imported images to the CDN, if supported."""
        raise NotImplementedError("todo: add cdn implementation")

    @staticmethod
    def _to_str(value: JsonValue) -> str:
        return str(value or "").strip()

    @staticmethod
    def _to_float(value: JsonValue) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)  # type: ignore
        except TypeError, ValueError:
            return None

    @staticmethod
    def _to_bool(value: JsonValue) -> bool:
        return bool(value)

    @staticmethod
    def _as_objects(values: JsonValue) -> list[JsonObject]:
        if not isinstance(values, list):
            return []
        return [row for row in values if isinstance(row, dict)]

    def import_into_db(
        self,
        db: TypeDAL,
        prio: int | ImportPriority | None = None,
        last_saved_by: str | None = None,
        mark_removed: bool | None = None,
        sync_cdn: bool = False,
    ) -> ImportStats:
        """Run the standardized import flow for this importer."""
        resolved_prio = ImportPriority.normalize(prio if prio is not None else self.priority)
        resolved_last_saved_by = last_saved_by or self.last_saved_by or self.source
        resolved_mark_removed = self.mark_removed if mark_removed is None else mark_removed

        self.before_import(db)
        supplier_stats = self.import_suppliers(db)
        stats = self.import_methods_and_products(
            db,
            prio=resolved_prio,
            last_saved_by=resolved_last_saved_by,
            mark_removed=resolved_mark_removed,
        )
        stats.suppliers = supplier_stats.suppliers
        self.after_methods_and_products_import(db, stats)
        vision_stats = self.import_visions(db)
        stats.visions = vision_stats.visions
        if sync_cdn:
            self.sync_images_to_cdn(db)
        self.after_import(db, stats)
        return stats

    def _log_import_event(
        self,
        action: str,
        supplier_gid: str,
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
        db: TypeDAL,
        prio: int | ImportPriority | None = None,
        last_saved_by: str | None = None,
        mark_removed: bool | None = None,
        **extras: t.Unpack[ImportRunExtras],
    ) -> ImportStats:
        """Run the import flow and persist a durable finished-run record."""
        started_at = dt.datetime.now()

        supplier_gid = extras["supplier_gid"]
        endpoint_type = extras.get("endpoint_type")
        job_key = extras.get("job_key")
        sync_cdn = extras.get("sync_cdn", True)

        supplier_name = resolve_supplier_name(supplier_gid)

        self._log_import_event(
            action="scraper-import-started",
            supplier_gid=supplier_gid,
            endpoint_type=endpoint_type,
            job_key=job_key,
            started_at=started_at,
        )

        try:
            stats = self.import_into_db(
                db,
                prio=prio,
                last_saved_by=last_saved_by,
                mark_removed=mark_removed,
                sync_cdn=sync_cdn,
            )
            record_importer_run(
                db,
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
            )
            self._log_import_event(
                action="scraper-import-finished",
                supplier_gid=supplier_gid,
                endpoint_type=endpoint_type,
                job_key=job_key,
                started_at=started_at,
                success=True,
            )
            return stats
        except Exception as exc:
            failure_message = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            self._log_import_event(
                action="scraper-import-failed",
                supplier_gid=supplier_gid,
                endpoint_type=endpoint_type,
                job_key=job_key,
                started_at=started_at,
                success=False,
                failure_message=failure_message,
            )
            with database_context(f"{self.source}.runlog.failure", ignore_errors=True) as log_db:
                record_importer_run(
                    log_db,
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
                )
            raise exc

    @classmethod
    def run(cls, **extras: t.Unpack[ImportRunExtras]) -> ImportStats:
        """Launch the importer in its configured database context."""
        importer = cls(**extras)
        with database_context(importer.source) as db:
            importer.applog = db.applog
            return importer.try_import_into_db(db, **extras)
