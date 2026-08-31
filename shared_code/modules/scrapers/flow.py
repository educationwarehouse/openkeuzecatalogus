"""Shared importer flow helpers for effective-dated scraper imports."""

import dataclasses as dc
import datetime as dt
import math
import re
import typing as t
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

from endow import Domain
from typedal import TypeDAL, TypedTable

from shared_code.data_model import Method, MethodEd, Predicate, Product, ProductEd, Supplier, Tagged, Vision
from shared_code.infra.database import DatabaseContext
from shared_code.migrations.migration_support import no_triggers
from shared_code.modules.scrapers.errors import ImportErrorCode, normalize_import_error_codes
from shared_code.modules.scrapers.types import (
    ChangeResult,
    ChangeStatus,
    ImportAuxStats,
    ImportMethod,
    ImportPriority,
    ImportProduct,
    ImportRunCountStat,
    ImportRunErrorStat,
    ImportStats,
    ImportSupplier,
    ImportTypeStats,
    ImportVision,
    to_err_prio,
)
from shared_code.services import ImageStorage

META_FIELDS = {"id", "gid", "last_saved_by", "effstatus", "effdt", "sync_gid", "prio", "created_at", "updated_at"}
# Standardized numeric tolerance for import comparisons (shared across all numeric fields).
NUMERIC_ABS_TOLERANCE = 0.005
GROEP_LEVEL_PATTERN = re.compile(r"^groep(?:\s+\d+)?$", flags=re.IGNORECASE)

KNOWN_BROKEN_DOMAINS = ("images.tlncdn.nl",)
KNOWN_BROKEN_DOMAINS_HTTP = tuple(f"http://{domain}/" for domain in KNOWN_BROKEN_DOMAINS)
KNOWN_BROKEN_DOMAINS_HTTPS = tuple(f"https://{domain}/" for domain in KNOWN_BROKEN_DOMAINS)


def normalize_level_name(level: t.Any) -> str | None:
    """Normalize a single level label to shared vocabulary."""
    if level is None:
        return None

    text = str(level).strip()
    if not text:
        return None

    if GROEP_LEVEL_PATTERN.match(text):
        return "PO"

    if text.casefold() == "po":
        return "PO"

    return text


def normalize_levels(levels: t.Any) -> list[str]:
    """Normalize and deduplicate level labels while preserving order."""
    if not isinstance(levels, list):
        return []

    normalized: list[str] = []
    for level in levels:
        normalized_level = normalize_level_name(level)
        if normalized_level and normalized_level not in normalized:
            normalized.append(normalized_level)

    return normalized


def _payload_fields(model_table: type[TypedTable], compare_exclude_columns: set[str]) -> list[str]:
    """Return business field names that can be compared/inserted for a model table."""
    field_names = (field.name for field in model_table)
    return [field for field in field_names if field not in META_FIELDS and field not in compare_exclude_columns]


def _validate_business_fields(table: type[TypedTable], payload: dict[str, t.Any]) -> dict[str, str]:
    """Validate non-meta payload fields for a typed table and return validation errors."""
    table_field_names = {field.name for field in table}
    business_payload = {
        key: value for key, value in payload.items() if key in table_field_names and key not in META_FIELDS
    }
    validation_errors, _ = table._validate_fields(business_payload)  # type: ignore

    return {
        str(field_name): str(error)
        for field_name, error in validation_errors.items()
        if str(field_name) not in META_FIELDS
    }


def _preload_gid_by_olid(model_table: type[TypedTable], olids: set[str]) -> dict[str, str]:
    """Preload a mapping from external `olid` to internal `gid` for known rows."""
    if not olids:
        return {}
    assert model_table.olid, "can't use `preload_gid_by_olid` on a table without olid"

    rows = model_table.where(model_table.olid.belongs(list(olids))).select(model_table.olid, model_table.gid)
    return {str(row.olid): str(row.gid) for row in rows if row.olid and row.gid}


def _seed_incoming_product_gids(products: list[ImportProduct], product_gid_by_olid: dict[str, str]) -> None:
    """Preseed gids for incoming products so intra-batch links are order-independent."""
    for product_data in products:
        olid = product_data.get("olid")
        if not isinstance(olid, str) or not olid:
            continue

        gid = product_data.get("gid")
        if gid:
            product_gid_by_olid[olid] = str(gid)
            continue

        if olid not in product_gid_by_olid:
            product_gid_by_olid[olid] = str(uuid.uuid4())


def _prepare_bundle_compositions(products: list[ImportProduct], product_gid_by_olid: dict[str, str]) -> set[str]:
    """Derive compositions from resolved bundle references before product persistence.

    A product with one or more resolvable bundle members is a package; every
    referenced member is a component; all other Edu-V products are single.
    References without a known product are ignored. A product that is both a
    package and a component is classified as a package, because it can itself
    be selected as a bundle.
    """
    bundle_source_gids: set[str] = set()
    bundle_parent_gids: set[str] = set()
    component_gids: set[str] = set()

    for product_data in products:
        if "bundle_product_olids" not in product_data:
            continue

        product_olid = product_data.get("olid")
        parent_gid = product_gid_by_olid.get(product_olid) if isinstance(product_olid, str) else None
        if not parent_gid:
            continue
        bundle_source_gids.add(parent_gid)

        bundle_product_olids = product_data.get("bundle_product_olids")
        if not isinstance(bundle_product_olids, list):
            continue

        resolved_component_gids = {
            product_gid_by_olid[product_olid]
            for product_olid in bundle_product_olids
            if isinstance(product_olid, str) and product_olid in product_gid_by_olid
        }
        if resolved_component_gids:
            bundle_parent_gids.add(parent_gid)
            component_gids.update(resolved_component_gids)

    for product_data in products:
        product_olid = product_data.get("olid")
        product_gid = product_gid_by_olid.get(product_olid) if isinstance(product_olid, str) else None
        if product_gid in bundle_parent_gids:
            product_data["composition"] = "package"
        elif product_gid in component_gids:
            product_data["composition"] = "component"
        elif "bundle_product_olids" in product_data:
            product_data["composition"] = "single"

    return bundle_source_gids


def _resolve_or_create_internal_gid(incoming_data: dict[str, t.Any], gid_by_olid: dict[str, str]) -> str | None:
    """Resolve a gid from incoming data or create one, caching newly created gids by olid."""
    gid = incoming_data.get("gid")
    if gid:
        return str(gid)

    olid = incoming_data.get("olid")
    if olid:
        existing_gid = gid_by_olid.get(str(olid))
        if existing_gid:
            return existing_gid

    created_gid = str(uuid.uuid4())
    if olid:
        gid_by_olid[str(olid)] = created_gid
    return created_gid


def _resolve_method_gid_from_olid(method_olid: str | None, method_gid_by_olid: dict[str, str]) -> str | None:
    """Resolve a method gid from `method_olid` via a preloaded mapping."""
    if not method_olid:
        return None
    return method_gid_by_olid.get(str(method_olid))


def _resolve_supplier_name(supplier_gid: str | None, supplier_name_by_gid: dict[str, str]) -> str | None:
    """Resolve a supplier name from the preloaded name map."""
    if not supplier_gid:
        return None
    return supplier_name_by_gid.get(str(supplier_gid))


def _build_error_stats(
    entity_type: str,
    error_codes: list[str],
    supplier_gid: str | None,
    supplier_name: str | None,
    entity_gid: str | None,
    entity_olid: str | None,
    entity_name: str | None,
    method_gid: str | None = None,
    method_name: str | None = None,
    validation_failed: bool = False,
    error_details: dict[str, t.Any] | None = None,
) -> list[ImportRunErrorStat]:
    """Build row-level importer error facts for one entity."""
    return [
        ImportRunErrorStat(
            entity_type=entity_type,
            error_code=error_code,
            supplier_gid=supplier_gid,
            supplier_name=supplier_name,
            entity_gid=entity_gid,
            entity_olid=entity_olid,
            entity_name=entity_name,
            method_gid=method_gid,
            method_name=method_name,
            validation_failed=validation_failed,
            error_details=error_details,
        )
        for error_code in error_codes
    ]


def _ed_table_for_model(model_table: type[TypedTable]) -> type[TypedTable]:
    """Resolve the typed `*_ed` table class for a typed `*_model` class."""
    db = model_table._db
    assert db, "can't use table without db"

    model_name = str(model_table._rname)
    ed_name = model_name.removesuffix("_model") + "_ed"
    ed_table = db.find_model(ed_name)
    if ed_table is None:
        raise ValueError(f"Could not resolve typed Ed table for model {model_name} (expected {ed_name})")
    return t.cast(type[TypedTable], ed_table)


def _values_differ(old_value: t.Any, new_value: t.Any) -> bool:
    """Return whether two values differ, with numeric tolerance for floats."""
    if isinstance(old_value, (int, float)) and isinstance(new_value, (int, float)):
        old_num = float(old_value)
        new_num = float(new_value)
        if math.isnan(old_num) or math.isnan(new_num):
            return old_value != new_value
        return abs(old_num - new_num) > NUMERIC_ABS_TOLERANCE
    return old_value != new_value


def _determine_changed(
    latest_same_prio: TypedTable,
    *,
    compare_exclude_columns: set[str],
    effstatus: bool,
    incoming_data: dict[str, t.Any],
    payload_fields: list[str],
) -> dict[str, tuple[t.Any, t.Any]]:
    compare_fields = [
        field for field in incoming_data if field not in compare_exclude_columns and field in set(payload_fields)
    ]
    changed_fields: dict[str, tuple[t.Any, t.Any]] = {}
    for field in compare_fields:
        old_value = getattr(latest_same_prio, field, None)
        new_value = incoming_data[field]
        if _values_differ(old_value, new_value):
            changed_fields[field] = (old_value, new_value)
    old_effstatus = bool(getattr(latest_same_prio, "effstatus", True))
    if old_effstatus != effstatus:
        changed_fields["effstatus"] = (old_effstatus, effstatus)
    return changed_fields


class ImportFlow(Domain):
    """Persist shared scraper payloads through the injected database and image storage."""

    db: DatabaseContext
    image_storage: ImageStorage

    def choose_image_url_for_import(
        self,
        current_url: str | None,
        incoming_url: str | None,
        upload_key: str,
    ) -> str | None:
        """Choose an image URL, preserving matching stored URLs across imports."""
        if incoming_url is None:
            return None

        if current_url and self.image_storage.is_file_url(current_url):
            normalized_incoming_url = normalize_image_source_url(incoming_url)
            if not normalized_incoming_url:
                return current_url

            if self.cdn_url_matches_source(
                current_cdn_url=current_url,
                upload_key=upload_key,
                source_url=normalized_incoming_url,
            ):
                return current_url

        return incoming_url

    def cdn_url_matches_source(
        self,
        current_cdn_url: str | None,
        upload_key: str,
        source_url: str | None,
    ) -> bool:
        """Return whether a stored URL is the deterministic upload for a source URL."""
        if not current_cdn_url or not source_url:
            return False
        elif current_cdn_url.startswith(("data:", "file://")):
            return True

        original_filename = Path(unquote(urlparse(source_url).path)).name or "image"
        filename = self.image_storage.create_filename(upload_key, original_filename)
        return current_cdn_url == self.image_storage.get_file_url(filename)

    def _resolve_image_url(
        self,
        gid: str,
        incoming_data: t.MutableMapping[str, t.Any],
        latest_or_current: TypedTable | None,
        model_table: type[TypedTable],
    ) -> None:
        current_image_url = getattr(latest_or_current, "image_url", None) if latest_or_current is not None else None
        raw_incoming_image_url = incoming_data.get("image_url")
        incoming_image_url = (
            raw_incoming_image_url
            if raw_incoming_image_url is None or isinstance(raw_incoming_image_url, str)
            else None
        )
        upload_key = gid
        if model_table is Product:
            upload_key = str(
                incoming_data.get("isbn")
                or (getattr(latest_or_current, "isbn", None) if latest_or_current is not None else None)
                or gid,
            )

        incoming_data["image_url"] = self.choose_image_url_for_import(
            current_url=current_image_url,
            incoming_url=incoming_image_url,
            upload_key=upload_key,
        )

    def insert_into_effdt_if_changed_for_prio(
        self,
        model_table: type[TypedTable],
        gid: str,
        incoming_data: dict[str, t.Any],
        *,
        prio: int | ImportPriority,
        last_saved_by: str,
        effstatus: bool = True,
        compare_exclude_columns: set[str] | None = None,
        verbose: bool = False,
    ) -> ChangeResult:
        """Insert a new effective-dated row when the incoming payload differs for a priority."""
        # note: this performs multiple row-level lookups and runs per imported item;
        #  but it's hard to optimize while looking for the latest truth
        ed_table = _ed_table_for_model(model_table)
        assert ed_table.effdt, f"{ed_table} is not effdt"

        resolved_prio = ImportPriority.normalize(prio)
        compare_exclude_columns = (compare_exclude_columns or set()) | META_FIELDS
        incoming_gid = incoming_data.get("gid")
        if incoming_gid is not None and str(incoming_gid) != str(gid):
            raise ValueError(f"incoming_data.gid ({incoming_gid}) does not match gid argument ({gid})")
        payload_fields = _payload_fields(model_table, compare_exclude_columns)

        latest_same_prio = (
            ed_table.where((ed_table.gid == gid) & (ed_table.prio == resolved_prio))
            .select(orderby=~ed_table.effdt, limitby=(0, 1))
            .first()
        )

        fallback_current = model_table.where(model_table.gid == gid).first()
        latest_or_current = latest_same_prio or fallback_current

        if "image_url" in incoming_data:
            self._resolve_image_url(gid, incoming_data, latest_or_current, model_table)

        is_new = latest_same_prio is None
        changed_fields = (
            _determine_changed(
                latest_same_prio,
                compare_exclude_columns=compare_exclude_columns,
                effstatus=effstatus,
                incoming_data=incoming_data,
                payload_fields=payload_fields,
            )
            if latest_same_prio
            else {}
        )

        if not (is_new or changed_fields):
            return ChangeResult(status=ChangeStatus.UNCHANGED)

        if verbose and not is_new:
            print(f"[import-changed] {ed_table._rname} gid={gid} changed_fields={changed_fields}")

        source_defaults = latest_same_prio or fallback_current
        to_insert = dict(incoming_data, gid=gid)
        if source_defaults is not None:
            for field in payload_fields:
                to_insert.setdefault(field, getattr(source_defaults, field, None))

        valid_fields = set(ed_table.fields) - {"id"}
        filtered_payload = {field: value for field, value in to_insert.items() if field in valid_fields}
        insert_payload = dict(
            filtered_payload,
            prio=resolved_prio,
            last_saved_by=last_saved_by,
            effstatus=effstatus,
            effdt=dt.datetime.now(),
        )

        validation_errors = _validate_business_fields(ed_table, insert_payload)
        if validation_errors:
            print(f"[import-invalid] {ed_table._rname} gid={gid} errors={validation_errors}")
            return ChangeResult(status=ChangeStatus.INVALID, validation_errors=validation_errors)

        ed_table.insert(**insert_payload)

        return ChangeResult(status=ChangeStatus.NEW if latest_same_prio is None else ChangeStatus.CHANGED)

    def upsert_visions(
        self,
        visions: list[ImportVision],
        *,
        prio: int | ImportPriority,
        last_saved_by: str,
    ) -> ImportAuxStats:
        """Upsert vision rows into the effective-dated ol_vision table."""
        incoming_olids = {str(v.get("olid")) for v in visions if v.get("olid")}
        gid_by_key = _preload_gid_by_vision_key(incoming_olids)

        stats = ImportAuxStats()
        for vision in visions:
            stats.seen += 1
            payload = {
                "olid": vision.get("olid"),
                "onderwijskwaliteit": vision.get("onderwijskwaliteit"),
                "visie": vision.get("visie"),
            }
            if not all((payload["olid"], payload["onderwijskwaliteit"], payload["visie"])):
                continue

            validation_errors = _validate_business_fields(Vision, payload)
            if validation_errors:
                print(f"[import-invalid] ol_vision olid={payload['olid']} errors={validation_errors}")
                stats.issues += 1
                continue

            key = (str(payload["olid"]), str(payload["onderwijskwaliteit"]))
            gid = gid_by_key.get(key)
            if not gid:
                gid = str(uuid.uuid4())
                gid_by_key[key] = gid

            status = self.insert_into_effdt_if_changed_for_prio(
                Vision,
                gid=gid,
                incoming_data=payload,
                prio=prio,
                last_saved_by=last_saved_by,
            )
            if status.status != ChangeStatus.UNCHANGED:
                stats.imported += 1
            if status.status == ChangeStatus.INVALID:
                stats.issues += 1
        return stats

    def upsert_suppliers(
        self,
        suppliers: list[ImportSupplier],
        *,
        prio: int | ImportPriority = ImportPriority.IMPORTER_OK,
        last_saved_by: str = "supplier-import",
        verbose: bool = False,
    ) -> ImportAuxStats:
        """Upsert supplier rows into the effective-dated supplier table."""
        stats = ImportAuxStats()
        resolved_prio = ImportPriority.normalize(prio)
        supplier_olids = {str(supplier.get("olid")) for supplier in suppliers if supplier.get("olid")}
        supplier_gid_by_olid = _preload_gid_by_olid(Supplier, supplier_olids)

        with no_triggers(self.db):
            for supplier in suppliers:
                stats.seen += 1
                payload = {
                    "gid": supplier.get("gid"),
                    "name": supplier.get("name"),
                    "logo_url": supplier.get("logo_url"),
                    "olid": supplier.get("olid"),
                    "status_visions": supplier.get("status_visions"),
                }
                if not all((payload["name"], payload["olid"], payload["status_visions"])):
                    stats.issues += 1
                    continue

                gid = _resolve_or_create_internal_gid(payload, supplier_gid_by_olid)
                if not gid:
                    stats.issues += 1
                    continue
                payload["gid"] = gid

                validation_errors = _validate_business_fields(Supplier, payload)
                if validation_errors:
                    print(f"[import-invalid] supplier gid={payload['gid']} errors={validation_errors}")
                    stats.issues += 1
                    continue

                status = self.insert_into_effdt_if_changed_for_prio(
                    Supplier,
                    gid=gid,
                    incoming_data=payload,
                    prio=resolved_prio,
                    last_saved_by=last_saved_by,
                    verbose=verbose,
                )
                if status.status != ChangeStatus.UNCHANGED:
                    stats.imported += 1
                elif status.status == ChangeStatus.INVALID:
                    stats.issues += 1

            rebuild_model(self.db, "supplier")
        return stats

    def mark_removed_with_prio(
        self,
        model_table: type[TypedTable],
        ed_table: type[TypedTable],
        *,
        prio: int | ImportPriority,
        incoming_gids: set[str],
        last_saved_by: str,
        supplier_gid: str | None = None,
    ) -> int:
        """Mark missing gids as removed for a priority and optional supplier."""
        resolved_prio = ImportPriority.normalize(prio)
        marked = 0
        active_gids = _gids_with_active_available_rows_at_prio(
            ed_table,
            prio=resolved_prio,
            supplier_gid=supplier_gid,
        )
        for gid in active_gids - incoming_gids:
            change_status = self.insert_into_effdt_if_changed_for_prio(
                model_table,
                gid,
                {"available": "verwijderd"},
                prio=resolved_prio,
                last_saved_by=last_saved_by,
            )
            if change_status.status not in {ChangeStatus.UNCHANGED, ChangeStatus.INVALID}:
                marked += 1
        return marked

    def import_methods(
        self,
        *,
        methods: list[ImportMethod],
        resolved_prio: int,
        method_stats: ImportTypeStats,
        last_saved_by: str,
        verbose: bool,
        method_name_by_gid: dict[str, str],
        method_gid_by_olid: dict[str, str],
        supplier_name_by_gid: dict[str, str],
        stats: ImportStats,
    ) -> set[str]:
        """Import method rows and collect their per-row statistics."""
        imported_method_gids: set[str] = set()
        for method_data in methods:
            method_stats.seen += 1
            method_data, method_errors = prepare_method_data(method_data, method_gid_by_olid=method_gid_by_olid)
            if not method_data:
                method_stats.skipped += 1
                continue

            gid = method_data["gid"]
            row_prio = to_err_prio(resolved_prio) if method_errors else resolved_prio

            change_status = self.insert_into_effdt_if_changed_for_prio(
                Method,
                gid,
                dict(method_data),
                prio=row_prio,
                last_saved_by=last_saved_by,
                verbose=verbose,
            )
            imported_method_gids.add(gid)
            _handle_change_status(change_status, method_errors, method_stats)

            if method_errors:
                method_stats.issues += 1

                supplier_gid = method_data.get("supplier_gid")

                stats.error_stats.extend(
                    _build_error_stats(
                        entity_type="method",
                        error_codes=normalize_import_error_codes(method_errors),
                        supplier_gid=supplier_gid,
                        supplier_name=supplier_name_by_gid.get(supplier_gid),
                        entity_gid=gid,
                        entity_olid=method_data.get("olid"),
                        entity_name=method_data.get("name"),
                        validation_failed=change_status.status == ChangeStatus.INVALID,
                        error_details=change_status.validation_errors,
                    ),
                )
            method_name_by_gid[gid] = method_data.get("name") or method_name_by_gid.get(gid, "")

        rebuild_model(self.db, "method")
        return imported_method_gids

    def import_products(
        self,
        *,
        product_gid_by_olid: dict[str, str],
        method_name_by_olid: dict[str, str],
        method_name_by_gid: dict[str, str],
        method_gid_by_olid: dict[str, str],
        supplier_name_by_gid: dict[str, str],
        resolved_prio: int,
        products: list[ImportProduct],
        product_stats: ImportTypeStats,
        last_saved_by: str,
        verbose: bool,
        stats: ImportStats,
    ) -> dict[str, int]:
        """Import product rows and collect their resolved row priorities by gid."""
        product_prio_by_gid: dict[str, int] = {}
        for product_data in products:
            product_stats.seen += 1

            product_data, product_errors = prepare_product_data(
                product_data,
                product_gid_by_olid=product_gid_by_olid,
                method_gid_by_olid=method_gid_by_olid,
            )
            if not product_data:
                product_stats.skipped += 1
                continue

            gid = product_data["gid"]
            row_prio = to_err_prio(resolved_prio) if product_errors else resolved_prio

            change_status = self.insert_into_effdt_if_changed_for_prio(
                Product,
                gid,
                dict(product_data),
                prio=row_prio,
                last_saved_by=last_saved_by,
                verbose=verbose,
            )
            product_prio_by_gid[gid] = row_prio
            _handle_change_status(change_status, product_errors, product_stats)

            if product_errors:
                product_stats.issues += 1

                method_gid = product_data.get("method_gid")
                supplier_gid = product_data.get("supplier_gid")

                stats.error_stats.extend(
                    _build_error_stats(
                        entity_type="product",
                        error_codes=normalize_import_error_codes(product_errors),
                        supplier_gid=supplier_gid,
                        supplier_name=_resolve_supplier_name(supplier_gid, supplier_name_by_gid),
                        entity_gid=gid,
                        entity_olid=product_data.get("olid"),
                        entity_name=product_data.get("name"),
                        method_gid=method_gid,
                        method_name=method_name_by_gid.get(method_gid)
                        or method_name_by_olid.get(product_data.get("method_olid")),
                        validation_failed=change_status.status == ChangeStatus.INVALID,
                        error_details=change_status.validation_errors,
                    ),
                )

        rebuild_model(self.db, "product")
        return product_prio_by_gid

    def import_bundle_relations(
        self,
        products: list[ImportProduct],
        product_gid_by_olid: dict[str, str],
        bundle_source_prio_by_gid: dict[str, int],
        last_saved_by: str,
        verbose: bool = False,
    ) -> None:
        """Synchronize Edu-V bundle references as effective-dated Tagged edges."""
        if not bundle_source_prio_by_gid:
            return

        bundle_source_gids = set(bundle_source_prio_by_gid)

        incoming_triples: set[tuple[str, str, str]] = set()
        for product_data in products:
            product_olid = product_data.get("olid")
            parent_gid = product_gid_by_olid.get(product_olid) if isinstance(product_olid, str) else None
            bundle_product_olids = product_data.get("bundle_product_olids")
            if not parent_gid or parent_gid not in bundle_source_gids or not isinstance(bundle_product_olids, list):
                continue

            incoming_triples.update(
                (parent_gid, Predicate.BUNDLES, product_gid_by_olid[component_olid])
                for component_olid in bundle_product_olids
                if isinstance(component_olid, str) and component_olid in product_gid_by_olid
            )

        existing_by_triple = {
            (row.subject_gid, row.predicate, row.object_gid): row.gid
            for row in Tagged.where(
                (Tagged.subject_gid.belongs(list(bundle_source_gids))) & (Tagged.predicate == Predicate.BUNDLES)
            ).select()
        }

        for subject_gid, _, object_gid in incoming_triples:
            Tagged.insert_relation_if_missing(
                subject_gid,
                Predicate.BUNDLES,
                object_gid,
                prio=bundle_source_prio_by_gid[subject_gid],
                last_saved_by=last_saved_by,
                comment="Edu-V bundled product",
            )

        for triple, gid in existing_by_triple.items():
            if triple in incoming_triples:
                continue
            self.insert_into_effdt_if_changed_for_prio(
                Tagged,
                gid,
                {"gid": gid},
                prio=bundle_source_prio_by_gid[triple[0]],
                last_saved_by=last_saved_by,
                effstatus=False,
                verbose=verbose,
            )

        self.db.executesql("select rebuild_tagged_model()")

    def mark_removed_methods_and_products(
        self,
        *,
        resolved_prio: int,
        imported_method_gids: set[str],
        imported_product_gids: set[str],
        last_saved_by: str,
        method_stats: ImportTypeStats,
        product_stats: ImportTypeStats,
        supplier_gid: str | None = None,
    ) -> None:
        """Mark missing method and product gids as removed for one import run."""
        method_removed = self.mark_removed_with_prio(
            model_table=Method,
            ed_table=MethodEd,
            prio=resolved_prio,
            incoming_gids=imported_method_gids,
            last_saved_by=last_saved_by,
            supplier_gid=supplier_gid,
        )
        method_stats.removed += method_removed
        rebuild_model(self.db, "method")

        product_removed = self.mark_removed_with_prio(
            model_table=Product,
            ed_table=ProductEd,
            prio=resolved_prio,
            incoming_gids=imported_product_gids,
            last_saved_by=last_saved_by,
            supplier_gid=supplier_gid,
        )
        product_stats.removed += product_removed
        rebuild_model(self.db, "product")

    def import_methods_and_products(
        self,
        *,
        methods: list[ImportMethod],
        products: list[ImportProduct],
        prio: int | ImportPriority,
        last_saved_by: str,
        mark_removed: bool = True,
        removed_supplier_gid: str | None = None,
        verbose: bool = False,
    ) -> ImportStats:
        """Import methods/products into effective-dated tables and rebuild models."""
        resolved_prio = ImportPriority.normalize(prio)
        stats = ImportStats()
        method_stats = stats.methods
        product_stats = stats.products
        method_olids = {str(olid) for method_data in methods if (olid := method_data.get("olid"))}
        product_olids = {str(olid) for product_data in products if (olid := product_data.get("olid"))}
        method_olids_from_products = {
            str(method_olid) for product_data in products if (method_olid := product_data.get("method_olid"))
        }
        linked_product_olids = {
            str(olid)
            for product_data in products
            for olid in (
                [product_data["follow_up_product_olid"]]
                if isinstance(product_data.get("follow_up_product_olid"), str)
                else []
            )
            if olid
        }
        for product_data in products:
            bundle_product_olids = product_data.get("bundle_product_olids")
            if isinstance(bundle_product_olids, list):
                linked_product_olids.update(
                    str(olid) for olid in bundle_product_olids if isinstance(olid, str) and olid
                )
            related_product_olids = product_data.get("related_product_olids")
            if isinstance(related_product_olids, list):
                linked_product_olids.update(
                    str(olid) for olid in related_product_olids if isinstance(olid, str) and olid
                )

        method_gid_by_olid = _preload_gid_by_olid(Method, method_olids | method_olids_from_products)
        product_gid_by_olid = _preload_gid_by_olid(Product, product_olids)
        product_gid_by_olid |= _preload_gid_by_olid(Product, linked_product_olids)
        _seed_incoming_product_gids(products, product_gid_by_olid)
        bundle_source_gids = _prepare_bundle_compositions(products, product_gid_by_olid)
        supplier_gids = {
            str(supplier_gid) for row in [*methods, *products] if (supplier_gid := row.get("supplier_gid"))
        }
        supplier_name_by_gid = {
            str(row.gid): str(row.name)
            for row in Supplier.where(Supplier.gid.belongs(list(supplier_gids))).select(Supplier.gid, Supplier.name)
            if row.gid and row.name
        }
        method_name_by_olid = {
            str(method_data.get("olid")): str(method_data.get("name"))
            for method_data in methods
            if method_data.get("olid") and method_data.get("name")
        }
        method_name_by_gid = {
            str(gid): method_name_by_olid[olid]
            for olid, gid in method_gid_by_olid.items()
            if olid in method_name_by_olid
        }

        with no_triggers(self.db):
            imported_method_gids = self.import_methods(
                methods=methods,
                resolved_prio=resolved_prio,
                method_stats=method_stats,
                last_saved_by=last_saved_by,
                verbose=verbose,
                method_name_by_gid=method_name_by_gid,
                method_gid_by_olid=method_gid_by_olid,
                supplier_name_by_gid=supplier_name_by_gid,
                stats=stats,
            )

        with no_triggers(self.db):
            product_prio_by_gid = self.import_products(
                product_gid_by_olid=product_gid_by_olid,
                method_name_by_olid=method_name_by_olid,
                method_name_by_gid=method_name_by_gid,
                method_gid_by_olid=method_gid_by_olid,
                supplier_name_by_gid=supplier_name_by_gid,
                resolved_prio=resolved_prio,
                products=products,
                product_stats=product_stats,
                last_saved_by=last_saved_by,
                verbose=verbose,
                stats=stats,
            )

        with no_triggers(self.db):
            self.import_bundle_relations(
                products=products,
                product_gid_by_olid=product_gid_by_olid,
                bundle_source_prio_by_gid={
                    gid: product_prio_by_gid[gid] for gid in bundle_source_gids if gid in product_prio_by_gid
                },
                last_saved_by=last_saved_by,
                verbose=verbose,
            )

        if mark_removed:
            with no_triggers(self.db):
                self.mark_removed_methods_and_products(
                    resolved_prio=resolved_prio,
                    imported_method_gids=imported_method_gids,
                    imported_product_gids=set(product_prio_by_gid),
                    last_saved_by=last_saved_by,
                    method_stats=method_stats,
                    product_stats=product_stats,
                    supplier_gid=removed_supplier_gid,
                )

        stats.count_stats.extend(
            _build_run_count_stats(count_key="method", count_label="Methode", type_stats=method_stats)
        )
        stats.count_stats.extend(
            _build_run_count_stats(count_key="product", count_label="Product", type_stats=product_stats),
        )

        self.db.commit()
        return stats


def rebuild_model(db: TypeDAL, table: t.Literal["method", "product", "supplier"]) -> None:
    """Rebuild the model table for methods, products or suppliers."""
    db.executesql(f"select rebuild_{table}_model()")


def _preload_gid_by_vision_key(olids: set[str]) -> dict[tuple[str, str], str]:
    """Preload a mapping from (olid, onderwijskwaliteit) to internal gid for known rows."""
    if not olids:
        return {}
    rows = Vision.where(Vision.olid.belongs(list(olids))).select(Vision.olid, Vision.onderwijskwaliteit, Vision.gid)
    return {
        (str(row.olid), str(row.onderwijskwaliteit)): str(row.gid)
        for row in rows
        if row.olid and row.onderwijskwaliteit and row.gid
    }


def normalize_image_source_url(url: str | None) -> str | None:
    """Normalize importer image URLs and filter sources that should not be mirrored."""
    if not url:
        return None

    if url.startswith(KNOWN_BROKEN_DOMAINS_HTTP) or url.startswith(KNOWN_BROKEN_DOMAINS_HTTPS):
        return None

    return url


def _build_run_count_stats(
    count_key: str,
    count_label: str,
    type_stats: ImportTypeStats,
) -> list[ImportRunCountStat]:
    return [
        ImportRunCountStat(
            count_type="run",
            count_key=count_key,
            count_label=count_label,
            metric=field.name,
            value=int(getattr(type_stats, field.name)),
        )
        for field in dc.fields(type_stats)
    ]


def _gids_with_active_available_rows_at_prio(
    ed_table: type[TypedTable],
    *,
    prio: int | ImportPriority,
    supplier_gid: str | None = None,
) -> set[str]:
    """Return active gids at a priority, optionally limited to one supplier."""
    return {
        gid
        for gid, _ in active_available_rows_at_prio(
            ed_table,
            prio=prio,
            supplier_gid=supplier_gid,
        )
    }


def active_available_rows_at_prio(
    ed_table: type[TypedTable],
    prio: int | ImportPriority,
    supplier_gid: str | None = None,
) -> list[tuple[str, str]]:
    """Return active, available gids and names at one priority and supplier."""
    db = ed_table._db
    assert db, "can't use a table without a db"

    resolved_prio = ImportPriority.normalize(prio)
    sql = f"""
        WITH ranked AS (
            SELECT
                gid,
                name,
                available,
                effstatus,
                ROW_NUMBER() OVER (PARTITION BY gid ORDER BY effdt DESC) AS row_nr
            FROM {ed_table._rname}
            WHERE prio = %(prio)s
              AND (%(supplier_gid)s IS NULL OR supplier_gid = %(supplier_gid)s)
        )
        SELECT gid, name
        FROM ranked
        WHERE row_nr = 1
          AND effstatus = 'T'
          AND COALESCE(available, '') != 'verwijderd'
    """  # noqa S608: all parameters are in our control so no SQL injection possible
    rows = db.executesql(sql, placeholders={"prio": resolved_prio, "supplier_gid": supplier_gid})
    return [(str(gid), str(name or gid)) for gid, name in rows]


def _handle_change_status(
    change_status: ChangeResult,
    errors: list[ImportErrorCode],
    stats: ImportTypeStats,
) -> None:
    if change_status.status == ChangeStatus.NEW:
        stats.new += 1
    elif change_status.status == ChangeStatus.CHANGED:
        stats.changed += 1
    elif change_status.status == ChangeStatus.INVALID:
        errors.append(ImportErrorCode.ROW_VALIDATION_FAILED)
    # else: unchanged


def prepare_method_data(
    method_data: ImportMethod,
    method_gid_by_olid: dict[str, str],
) -> tuple[ImportMethod | None, list[ImportErrorCode]]:
    """Apply final transformations/lookups/checks before inserting into the database."""
    if "levels" in method_data:
        method_data["levels"] = normalize_levels(method_data.get("levels"))

    method_errors = t.cast(list[ImportErrorCode], method_data.pop("_errors", []))

    gid = _resolve_or_create_internal_gid(method_data, method_gid_by_olid)
    if not gid:
        return None, method_errors

    method_data["gid"] = gid
    method_data["import_error_codes"] = method_errors

    return method_data, method_errors


def prepare_product_data(
    product_data: ImportProduct,
    product_gid_by_olid: dict[str, str],
    method_gid_by_olid: dict[str, str],
) -> tuple[ImportProduct | None, list[ImportErrorCode]]:
    """Apply final transformations/lookups/checks before inserting into the database."""
    if "levels" in product_data:
        product_data["levels"] = normalize_levels(product_data.get("levels"))

    raw_errors: list[ImportErrorCode] = product_data.pop("_errors", [])
    row_errors = list(raw_errors) if isinstance(raw_errors, list) else []

    if not product_data.get("method_gid"):
        product_data["method_gid"] = _resolve_method_gid_from_olid(product_data.get("method_olid"), method_gid_by_olid)

    if not product_data.get("method_gid"):
        row_errors.append(ImportErrorCode.METHOD_LINK_MISSING)

    follow_up_product_olid = product_data.pop("follow_up_product_olid", None)
    if isinstance(follow_up_product_olid, str):
        product_data["follow_up_product"] = product_gid_by_olid.get(follow_up_product_olid)

    related_product_olids = product_data.pop("related_product_olids", [])
    if isinstance(related_product_olids, list):
        product_data["related_products"] = [
            product_gid_by_olid[olid]
            for olid in related_product_olids
            if isinstance(olid, str) and olid in product_gid_by_olid
        ]

    gid = _resolve_or_create_internal_gid(product_data, product_gid_by_olid)
    if not gid:
        return None, row_errors

    product_data["gid"] = gid
    product_data["import_error_codes"] = row_errors

    return product_data, row_errors
