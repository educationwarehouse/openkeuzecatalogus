"""Edu-V importer implementation."""

import typing as t
from collections import defaultdict

from is_isbn.is_isbn import is_isbn
from yayarl import URL

from shared_code.data_model import Supplier
from shared_code.infra.http import fetch_json_payload
from shared_code.modules.scrapers.abs import AbstractImporter
from shared_code.modules.scrapers.errors import ImportErrorCode
from shared_code.modules.scrapers.types import ImportMethod, ImportProduct, JsonObject
from shared_code.util import olid


class EduVImporter(AbstractImporter):
    """Import Edu-V catalogue data into the shared schema."""

    # https://edu-v.atlassian.net/wiki/spaces/AFSPRAKENS/pages/634421249/Catalogue+API

    source = "edu-v-import"
    base_url: str  # e.g. https://app.cumulus.co/api/edu-v/v1/
    supplier_gid: str | None = None
    products_endpoint = "products"
    timeout_seconds = 30.0
    _products_cache: list[JsonObject] | None = None

    def __init__(self, base_url: str, supplier_gid: str | None = None, **_: t.Any) -> None:
        """Store connection settings for the Edu-V API."""
        super().__init__()
        self.base_url = base_url
        if supplier_gid:
            self.supplier_gid = supplier_gid

    @classmethod
    def _extract_levels(cls, product: JsonObject) -> list[str]:
        levels: set[str] = set()
        studies = cls._as_objects(product.get("studies", []))
        for study in studies:
            study_levels = cls._as_objects(study.get("studyLevels", []))
            for level in study_levels:
                level_name = cls._to_str(level.get("studyLevelName"))
                if level_name:
                    levels.add(level_name.lower())
        return sorted(levels)

    @classmethod
    def _extract_subjects(cls, product: JsonObject) -> list[str]:
        subjects: set[str] = set()
        subject_rows = cls._as_objects(product.get("subjects", []))
        for subject in subject_rows:
            subject_name = cls._to_str(subject.get("subjectName"))
            if subject_name:
                subjects.add(subject_name)
        return sorted(subjects)

    @classmethod
    def _extract_price(cls, product: JsonObject) -> float | None:
        price_rows = cls._as_objects(product.get("price", []))
        if not price_rows:
            return None
        first_price = price_rows[0]
        return cls._to_float(first_price.get("priceIncl")) or cls._to_float(
            first_price.get("priceExcl"),
        )

    @classmethod
    def _extract_image_url(cls, product: JsonObject) -> str | None:
        media = product.get("media")
        if not isinstance(media, dict):
            return None
        main = media.get("mainThumbnailUrl")
        if not isinstance(main, dict):
            return None
        url = main.get("url")
        return str(url) if isinstance(url, str) else None

    def _supplier_gid(self, publisher_name: str) -> str:
        if self.supplier_gid:
            return self.supplier_gid

        if (publisher := self._to_str(publisher_name)) and (
            exact := Supplier.where(Supplier.name.lower() == publisher.lower()).select(Supplier.gid).first()
        ):
            return str(exact.gid)

        raise ValueError(f"Supplier not found in database for publisher={publisher!r}")

    @classmethod
    def _method_key(cls, publisher_name: str, family_name: str) -> str:
        return f"{publisher_name.lower()}:{family_name.lower()}"

    @classmethod
    def _to_isbn_or_none(cls, value: str) -> str | None:
        return value if is_isbn(value) else None

    @classmethod
    def _extract_bouw(cls, levels: list[str]) -> list[str]:
        result: set[str] = set()
        for level in levels:
            normalized = level.lower()
            if " " not in normalized:
                continue
            _, year_raw = normalized.rsplit(" ", 1)
            if not year_raw.isdigit():
                continue
            year = int(year_raw)
            if year >= 4:
                result.add("bovenbouw")
            else:
                result.add("onderbouw")
        return sorted(result)

    @classmethod
    def _is_tto(cls, levels: list[str]) -> bool:
        return any("tto" in level.lower() for level in levels)

    def _map_status(self, status: str | None) -> str | None:
        """Map Edu-V status values to the internal availability vocabulary."""
        if not status:
            return None
        normalized = status.strip().lower()
        mapping = {
            "not-yet-available": "nog niet leverbaar",
            "limited-available": "beperkt leverbaar",
            "available": "leverbaar",
            "temporary-not-available": "niet leverbaar",
            "no-longer-available": "binnenkort niet meer leverbaar",
            "will-never-be-available": "verwijderd",
            "not-available-or-usable": "niet leverbaar",
        }
        return mapping.get(normalized, "onbekend")

    @classmethod
    def _physical_digital_mix(cls, product_type: str) -> str:
        kind = product_type.lower()

        if kind in ("digital", "physical"):
            return kind
        else:
            return "mix"

    @classmethod
    def _license_duration(cls, license_period: t.Any) -> str | None:
        if not isinstance(license_period, dict):
            return str(license_period)

        variant = cls._to_str(license_period.get("licenseVariant")) or None

        if variant == "days":
            days = license_period.get("licenseDays")
            return f"{days} dagen"

        return {"month": "1 maand", "year": "1 jaar", "schoolyear": "1 schooljaar (tot 31 juli)"}.get(variant, variant)

    def _fetch_products_payload(self) -> list[JsonObject]:
        if self._products_cache is not None:
            return self._products_cache

        if not self.base_url:
            raise ValueError(f"{self.__class__.__name__}.base_url is not configured")

        url = URL(self.base_url) / self.products_endpoint

        payload = fetch_json_payload(
            url,
            timeout=self.timeout_seconds,
            headers={"Accept": "application/json"},
            allow_redirects=True,
        )

        if isinstance(payload, list):
            rows = self._as_objects(payload)
        elif isinstance(payload, dict):
            rows = (
                self._as_objects(payload.get("products"))
                or self._as_objects(payload.get("items"))
                or self._as_objects(payload.get("results"))
                or self._as_objects(payload.get("data"))
            )
        else:
            rows = []

        self._products_cache = rows
        return rows

    def fetch_products(self) -> list[ImportProduct]:
        """Fetch Edu-V products and normalize them into import payloads."""
        rows = self._fetch_products_payload()
        products: list[JsonObject] = []
        for row in rows:
            errors: list[ImportErrorCode] = []
            external_product_id = self._to_str(row.get("productId"))
            product_name = self._to_str(row.get("name"))
            publisher = self._to_str(row.get("publisher")) or "unknown"
            family_name = self._to_str(row.get("productFamilyName")) or product_name

            if not (external_product_id and product_name):
                continue

            supplier_gid = self._supplier_gid(publisher)
            method_key = self._method_key(publisher, family_name)
            method_olid = olid.generate("method", method_key)
            level_x_year = self._extract_levels(row)
            levels = [level.split(" ")[0] for level in level_x_year]
            bouw = self._extract_bouw(level_x_year)

            product_type = self._to_str(row.get("type"))
            source_status = self._to_str(row.get("status"))
            mapped_status = self._map_status(source_status or None)

            activation_period = row.get("licensePeriod") or {}
            has_license_variant = (
                bool(self._to_str(activation_period.get("licenseVariant")))
                if isinstance(activation_period, dict)
                else False
            )

            activation_period = row.get("activationPeriod") or {}
            has_activation_variant = (
                bool(self._to_str(activation_period.get("activationVariant")))
                if isinstance(activation_period, dict)
                else False
            )

            if source_status and mapped_status == "onbekend":
                errors.append(ImportErrorCode.STATUS_UNKNOWN)

            if self._as_objects(row.get("studies", [])) and not level_x_year:
                errors.append(ImportErrorCode.LEVELS_PARSE_FAILED)

            if level_x_year and not bouw:
                errors.append(ImportErrorCode.BOUW_PARSE_FAILED)

            if product_type == "physical" and (not has_license_variant or not has_activation_variant):
                errors.append(ImportErrorCode.LICENSE_ACTIVATION_MISSING)

            isbn_or_ean = self._to_isbn_or_none(external_product_id)
            product_olid = (
                olid.generate("isbn", isbn_or_ean) if isbn_or_ean else olid.generate("eduv", external_product_id)
            )

            products.append(
                {
                    # internal gid is resolved in importer_flow.py
                    "name": product_name,
                    "supplier_gid": supplier_gid,
                    "method_olid": method_olid,
                    "isbn": isbn_or_ean,
                    "olid": product_olid,
                    "available": mapped_status or None,
                    "levels": levels,
                    "level_x_year": level_x_year,
                    "subjects": self._extract_subjects(row),
                    "image_url": self._extract_image_url(row),
                    "description": self._to_str(row.get("longDescription")) or None,
                    "sample_copies_link": self._to_str(row.get("trialAccessUrl")) or None,
                    "more_information": self._to_str(row.get("defaultAccessUrl")) or None,
                    "physical_digital_mix": self._physical_digital_mix(product_type),
                    "digital_folio_mix": row.get("productUsages") or [],
                    "recommended_price": self._extract_price(row),
                    "priority": 3 if self._to_bool(row.get("forSale")) else 1,
                    "bouw": bouw,
                    "tto": self._is_tto(levels),
                    "demo_environment_link": self._to_str(row.get("defaultAccessUrl")) or None,
                    "license_duration": self._license_duration(row.get("licensePeriod") or {}),
                    "composition": "single",
                    # intendedEndUserRole = document/student
                    "_errors": errors,
                },
            )

        return t.cast(list[ImportProduct], products)

    def fetch_methods(self) -> list[ImportMethod]:
        """Group Edu-V products into the shared method payload shape."""
        products = t.cast(list[JsonObject], self.fetch_products())
        grouped: dict[str, list[JsonObject]] = defaultdict(list)
        for product in products:
            method_olid = self._to_str(product.get("method_olid"))
            if method_olid:
                grouped[method_olid].append(product)

        methods: list[JsonObject] = []
        for method_olid, product_rows in grouped.items():
            first = product_rows[0]
            levels = sorted({level for row in product_rows for level in t.cast(list[str], row.get("levels", []))})
            level_x_years = sorted(
                {level for row in product_rows for level in t.cast(list[str], row.get("level_x_year", []))}
            )
            subjects = sorted(
                {subject for row in product_rows for subject in t.cast(list[str], row.get("subjects", []))},
            )
            mixes = {
                self._to_str(row.get("physical_digital_mix")) for row in product_rows if row.get("physical_digital_mix")
            }
            delivery_types = sorted(
                {
                    entry
                    for row in product_rows
                    for entry in t.cast(list[str], row.get("digital_folio_mix", []))
                    if isinstance(entry, str) and entry
                },
            )
            # prices = [
            #     t.cast(float, row["recommended_price"])
            #     for row in product_rows
            #     if row.get("recommended_price") is not None
            # ]

            physical_digital_mix = "mix" if len(mixes) > 1 else next(iter(mixes), "mix")

            methods.append(
                {
                    # internal gid is resolved in importer_flow.py
                    "name": self._to_str(first.get("name")).split("licentie", 1)[-1].strip().capitalize()
                    or self._to_str(first.get("name")),
                    "supplier_gid": first.get("supplier_gid"),
                    "olid": method_olid,
                    "available": first.get("available"),
                    "description": first.get("description"),
                    "levels": levels,
                    "subjects": subjects,
                    "image_url": first.get("image_url"),
                    "sample_copies": first.get("sample_copies_link"),
                    "preview_digital_environment": first.get("more_information"),
                    "more_information": first.get("more_information"),
                    # note: no price
                    "physical_digital_mix": physical_digital_mix,
                    "digital_folio_mix": delivery_types,
                    "priority": max(row.get("priority", 1) for row in product_rows),
                    "bouw": self._extract_bouw(level_x_years),
                    "tto": self._is_tto(levels),
                },
            )

        return t.cast(list[ImportMethod], methods)
