"""Importer for the shared Kennisnet Edu-V catalogue."""

import dataclasses as dc
import typing as t

from typedal import TypedRows
from yayarl import URL

from shared_code.data_model.tables import ImporterRun, ImporterRunEvent, KennisnetCoverageStatus, Supplier
from shared_code.modules.scrapers.abs import AbstractImporter
from shared_code.modules.scrapers.eduv import EduVFileVersion, fetch_eduv_products
from shared_code.modules.scrapers.eduv.json_import import EduVPayloadImporter
from shared_code.modules.scrapers.errors import ImportWarningCode
from shared_code.modules.scrapers.kennisnet import KENNISNET_CATALOGUE_BASE_URL
from shared_code.modules.scrapers.types import (
    CdnImageUploadStats,
    ImportMethod,
    ImportProduct,
    ImportRunCountStat,
    ImportStats,
    JsonObject,
)
from shared_code.util.lists import uniq

KENNISNET_IMPORTER_TYPES = ("edu-v-kennisnet-v1", "edu-v-kennisnet-v2")


class KennisnetPublisherObservation(t.TypedDict):
    """One publisher's catalogue and local-coverage snapshot."""

    publisher: str
    version: str
    coverage_status: KennisnetCoverageStatus
    local_supplier_gids: list[str]
    local_supplier_names: list[str]
    product_count: int
    method_count: int


def kennisnet_eduv_version(endpoint_type: str) -> EduVFileVersion:
    """Derive the Edu-V version from a known Kennisnet importer type."""
    if endpoint_type not in KENNISNET_IMPORTER_TYPES:
        raise ValueError(f"Unknown Kennisnet importer type: {endpoint_type}")
    return t.cast(EduVFileVersion, endpoint_type.rsplit("-", maxsplit=1)[-1])


class KennisnetCatalogueImporter(AbstractImporter):
    """Import selected suppliers from one paginated Kennisnet catalogue scan per version."""

    source = "edu-v-kennisnet-import"
    prune_aggregate_runs = True

    def __init__(
        self,
        supplier_gid: str | None = None,
        base_url: URL | str | None = None,
        **extras: t.Any,
    ) -> None:
        """Initialize a supplier-scoped or aggregate Kennisnet catalogue import."""
        super().__init__(**extras)
        self.supplier_gid = supplier_gid
        self.base_url = URL(base_url) if base_url else KENNISNET_CATALOGUE_BASE_URL
        self.selected_supplier_gids: set[str] = set()
        self.known_publishers: set[str] = set()
        self.matched_supplier_gids: set[str] = set()
        self.publisher_observations: list[KennisnetPublisherObservation] = []
        self.products: list[ImportProduct] | None = None
        self.methods: list[ImportMethod] | None = None
        self.selected_supplier_names: dict[str, str] = {}
        self.progress_event_gid: str | None = None

    @classmethod
    def from_env(
        cls,
        supplier_gid: str | None = None,
        base_url: URL | str | None = None,
    ) -> t.Self:
        """Build the importer with the optional aggregate-run scope and endpoint."""
        return cls(supplier_gid=supplier_gid, base_url=base_url)

    def before_import(self) -> None:
        """Fetch and normalize all selected catalogue rows before modifying the database."""
        self.report("Fetching catalogue rows")
        self._prepare_catalogue()

    def fetch_products(self) -> list[ImportProduct]:
        """Return the cached normalized products for every selected supplier."""
        self._prepare_catalogue()
        return self.products or []

    def fetch_methods(self) -> list[ImportMethod]:
        """Return the cached normalized methods for every selected supplier."""
        self._prepare_catalogue()
        self.report("Saving methods and products")
        return self.methods or []

    def sync_images_to_cdn(self) -> CdnImageUploadStats:
        """Synchronize images for each selected supplier after the aggregate import."""
        if self.supplier_gid:
            return super().sync_images_to_cdn()

        stats = CdnImageUploadStats()
        try:
            for supplier_number, selected_supplier_gid in enumerate(self.selected_supplier_gids, start=1):
                self.supplier_gid = selected_supplier_gid
                supplier_name = self.selected_supplier_names.get(selected_supplier_gid, selected_supplier_gid)
                self.report(
                    f"Uploading images for supplier {supplier_number}/"
                    f"{len(self.selected_supplier_gids)}: {supplier_name}"
                )
                supplier_stats = super().sync_images_to_cdn()
                for field in dc.fields(stats):
                    setattr(stats, field.name, getattr(stats, field.name) + getattr(supplier_stats, field.name))
                self._update_image_progress(supplier_number)
                self.report(f"Uploaded {supplier_stats.uploaded} images for {supplier_name}")
        finally:
            self.supplier_gid = None
        return stats

    def after_import(self, stats: ImportStats) -> None:
        """Add Kennisnet catalogue coverage facts to the aggregate result."""
        stats.count_stats.extend(
            [
                ImportRunCountStat(
                    count_type="kennisnet_catalogue",
                    count_key="publisher",
                    count_label="Kennisnet-uitgevers",
                    metric="known",
                    value=len(self.known_publishers),
                ),
                ImportRunCountStat(
                    count_type="kennisnet_catalogue",
                    count_key="supplier",
                    count_label="Lokale leveranciers",
                    metric="configured",
                    value=len(self.selected_supplier_gids),
                ),
                ImportRunCountStat(
                    count_type="kennisnet_catalogue",
                    count_key="supplier",
                    count_label="Lokale leveranciers",
                    metric="matched",
                    value=len(self.matched_supplier_gids),
                ),
            ],
        )

    def after_methods_and_products_import(self, stats: ImportStats) -> None:
        """Expose completed catalogue counts while CDN uploads continue."""
        assert self.run_gid, "The import run should be created before methods and products finish importing"
        ImporterRun.where(ImporterRun.gid == self.run_gid).update(phase="images")
        self.progress_event_gid = ImporterRunEvent.insert(
            run_gid=self.run_gid,
            event_type="progress",
            metric="live",
            entity_type="import",
            value=0,
            details={
                "methods_seen": stats.methods.seen,
                "methods_issues": stats.methods.issues,
                "products_seen": stats.products.seen,
                "products_issues": stats.products.issues,
                "image_suppliers_total": len(self.selected_supplier_gids),
            },
        ).gid
        self.db.commit()

    def after_run_logged(self, run_gid: str, stats: ImportStats | None) -> None:
        """Persist the publisher coverage snapshot alongside this importer run."""
        for observation in self.publisher_observations:
            ImporterRunEvent.insert(
                run_gid=run_gid,
                event_type="observation",
                metric="coverage",
                entity_type="publisher",
                entity_name=observation["publisher"],
                details=dict(observation),
            )
        self.db.commit()

    def report(self, message: str) -> None:
        """Print one concise progress update for the queue worker log."""
        print(f"[{self.source}] {message}", flush=True)

    def _update_image_progress(self, supplier_number: int) -> None:
        assert self.progress_event_gid, "The image progress event should exist before image uploads report progress"
        ImporterRunEvent.where(ImporterRunEvent.gid == self.progress_event_gid).update(value=supplier_number)
        self.db.commit()

    def _report_supplier_warnings(self, payload_importer: EduVPayloadImporter, supplier: Supplier) -> None:
        """Forward payload warnings with the supplier context used by this catalogue."""
        for warning in payload_importer._warnings:
            self._warn_import(
                warning_code=warning.warning_code,
                message=warning.message,
                product_name=warning.product_name,
                reason=warning.reason,
                source_url=warning.source_url,
                supplier_gid=supplier.gid,
                supplier_name=supplier.name,
                entity_type=warning.entity_type,
                entity_gid=warning.entity_gid,
                entity_olid=warning.entity_olid,
            )

    def _prepare_catalogue(self) -> None:
        if self.products is not None and self.methods is not None:
            return

        suppliers = self._selected_suppliers()
        local_suppliers = Supplier.select(orderby=Supplier.name).collect()
        self._validate_supplier_configuration(suppliers)
        self.selected_supplier_gids = {supplier.gid for supplier in suppliers if supplier.gid}
        self.selected_supplier_names = {
            supplier.gid: supplier.name or supplier.gid for supplier in suppliers if supplier.gid
        }

        products: list[ImportProduct] = []
        methods: list[ImportMethod] = []
        reconciled_supplier_gids: set[str] = set()
        for endpoint_type in KENNISNET_IMPORTER_TYPES:
            version_suppliers = [supplier for supplier in suppliers if supplier.endpoint_type == endpoint_type]
            if not version_suppliers:
                continue
            version = kennisnet_eduv_version(endpoint_type)

            rows_by_publisher = self._rows_by_publisher(
                fetch_eduv_products(
                    self.base_url / version / "products",
                    uses_pagination=True,
                    on_invalid_row=lambda index, row: self._warn_import(
                        warning_code=ImportWarningCode.EDUV_PRODUCT_ROW_SKIPPED,
                        message=f"Skipped Edu-V product row {index}: expected an object, got {type(row).__name__}.",
                        reason=repr(row),
                    ),
                    on_page=lambda page_number, page_size, total_rows, version=version: self.report(
                        f"Fetched Edu-V {version} page {page_number}: {page_size} rows, {total_rows} total"
                    ),
                )
            )
            self.known_publishers.update(rows_by_publisher)
            self.report(
                f"Fetched Edu-V {version}: {sum(len(rows) for rows in rows_by_publisher.values())} rows, "
                f"{len(rows_by_publisher)} publishers"
            )
            self._record_publisher_observations(
                version=version,
                rows_by_publisher=rows_by_publisher,
                local_suppliers=local_suppliers,
            )

            for supplier in version_suppliers:
                publisher = (supplier.endpoint_publisher or "").strip()
                if publisher not in rows_by_publisher:
                    self._warn_import(
                        warning_code=ImportWarningCode.EDUV_PUBLISHER_MISSING,
                        message=f"Kennisnet uitgever {publisher!r} voor leverancier {supplier.name!r} ontbreekt; "
                        "bestaande leermiddelen blijven behouden.",
                    )
                    continue
                self.report(f"Normalizing {supplier.name}: {len(rows_by_publisher.get(publisher, []))} rows")
                if publisher in rows_by_publisher and supplier.gid:
                    self.matched_supplier_gids.add(supplier.gid)
                payload_importer = EduVPayloadImporter(
                    payload={"products": rows_by_publisher.get(publisher, [])},
                    version=version,
                    supplier_gid=supplier.gid,
                )
                supplier_products = payload_importer.fetch_products()
                products.extend(supplier_products)
                methods.extend(payload_importer.fetch_methods())
                self._report_supplier_warnings(payload_importer, supplier)
                validation_errors = payload_importer.validation_errors()
                if not validation_errors:
                    reconciled_supplier_gids.add(supplier.gid)

        self.products = products
        self.methods = methods
        self.removed_supplier_gids = reconciled_supplier_gids

    def _record_publisher_observations(
        self,
        *,
        version: str,
        rows_by_publisher: dict[str, list[JsonObject]],
        local_suppliers: t.Iterable[Supplier],
    ) -> None:
        """Snapshot the local coverage of every publisher returned by Kennisnet."""
        for publisher, publisher_rows in rows_by_publisher.items():
            matches = [
                supplier
                for supplier in local_suppliers
                if publisher == supplier.name or publisher == supplier.endpoint_publisher
            ]
            self.publisher_observations.append(
                KennisnetPublisherObservation(
                    publisher=publisher,
                    version=version,
                    coverage_status=self._coverage_status(matches, version),
                    local_supplier_gids=[supplier.gid for supplier in matches if supplier.gid],
                    local_supplier_names=[supplier.name for supplier in matches if supplier.name],
                    product_count=len(publisher_rows),
                    method_count=0,
                )
            )

    def _selected_suppliers(self) -> TypedRows[Supplier]:
        query = Supplier.endpoint_type.belongs(KENNISNET_IMPORTER_TYPES)
        if self.supplier_gid:
            query &= Supplier.gid == self.supplier_gid
        return Supplier.where(query).select(orderby=Supplier.name).collect()

    @staticmethod
    def _coverage_status(suppliers: list[Supplier], version: str) -> KennisnetCoverageStatus:
        """Classify a Kennisnet publisher against its local supplier matches."""
        if any(supplier.endpoint_type == f"edu-v-kennisnet-{version}" for supplier in suppliers):
            return KennisnetCoverageStatus.IMPORTED
        elif any(supplier.endpoint_type == "edu-v" for supplier in suppliers):
            return KennisnetCoverageStatus.OWN_ENDPOINT
        elif suppliers:
            return KennisnetCoverageStatus.UNCONFIGURED
        else:
            return KennisnetCoverageStatus.UNKNOWN

    @staticmethod
    def _validate_supplier_configuration(suppliers: t.Iterable[Supplier]) -> None:
        publishers_by_type: dict[str, list[str]] = {}
        for supplier in suppliers:
            publisher = (supplier.endpoint_publisher or "").strip()
            if not publisher:
                raise ValueError(f"Kennisnet supplier {supplier.name!r} has no publisher filter configured.")
            publishers_by_type.setdefault(supplier.endpoint_type, []).append(publisher)

        duplicates = [
            f"{endpoint_type}: {publisher}"
            for endpoint_type, publishers in publishers_by_type.items()
            for publisher in uniq(publishers)
            if publishers.count(publisher) > 1
        ]
        if duplicates:
            raise ValueError(f"Duplicate Kennisnet publisher filters: {', '.join(duplicates)}")

    def _rows_by_publisher(self, rows: list[JsonObject]) -> dict[str, list[JsonObject]]:
        grouped: dict[str, list[JsonObject]] = {}
        for index, row in enumerate(rows, start=1):
            publisher = row.get("publisher")
            if not isinstance(publisher, str) or not publisher.strip():
                self._warn_import(
                    warning_code=ImportWarningCode.EDUV_PRODUCT_ROW_SKIPPED,
                    message=f"Skipped Edu-V product row {index}: publisher is missing or invalid.",
                    reason=repr(row),
                )
                continue
            grouped.setdefault(publisher.strip(), []).append(row)
        return grouped


__all__ = [
    "KENNISNET_CATALOGUE_BASE_URL",
    "KENNISNET_IMPORTER_TYPES",
    "KennisnetCatalogueImporter",
    "kennisnet_eduv_version",
]
