"""Edu-V importer implementation."""

import abc
import datetime as dt
import re
import typing as t
from collections import defaultdict

from pydantic import BaseModel, Field, PrivateAttr, ValidationError
from pydantic.fields import FieldInfo
from yayarl import URL

from shared_code.infra.http import fetch_json_payload
from shared_code.modules.scrapers.abs import AbstractImporter
from shared_code.modules.scrapers.eduv.generated import catalogue_v1_1_0, catalogue_v2_0_0
from shared_code.modules.scrapers.errors import ImportErrorCode, ImportWarningCode
from shared_code.modules.scrapers.types import ImportMethod, ImportProduct, JsonObject
from shared_code.util import olid
from shared_code.util.lists import uniq

type EduVProductModel = catalogue_v1_1_0.Product | catalogue_v2_0_0.Product
type EduVProductID = catalogue_v1_1_0.ProductID | catalogue_v2_0_0.ProductID

EduVFileVersion = t.Literal["v1", "v2"]

STATUS_MAPPING = {
    "available": "leverbaar",
    "limited-available": "beperkt leverbaar",
    "not-yet-available": "nog niet leverbaar",
    "temporary-not-available": "niet leverbaar",
    "no-longer-available": "niet leverbaar",
    "will-never-be-available": "niet leverbaar",
    "not-available-or-usable": "niet leverbaar",
    # 'verwijderd' is wanneer een product helemaal niet meer in de dataset zit.
}
EDUV_VERSION_RE = re.compile(r"/v(\d+)(?:\.(\d+))?(?:\.(\d+))?")
PLAIN_VERSION_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?$")
LEVEL_YEAR_RE = re.compile(r"^(?P<level>.*?)(?:(?:,\s*|\s+)(?P<year>\d+))?$")
TTO_LEVEL_RE = re.compile(r"[-\s]*\btto\b[-\s]*", re.IGNORECASE)
CATALOG_LEVELS = frozenset(("pro", "vmbo-bb", "vmbo-kb", "vmbo-gl", "vmbo-tl", "havo", "vwo"))
MAX_EDUV_PRODUCT_PAGES = 10_000


def fetch_eduv_product_page(url: URL, timeout_seconds: float = 30.0) -> list[t.Any]:
    """Fetch one Edu-V page containing a product list or a products envelope."""
    payload = fetch_json_payload(url, timeout=timeout_seconds)
    if isinstance(payload, dict):
        if "products" not in payload:
            raise ValueError(
                f"Edu-V products endpoint object must contain a 'products' key, got keys: {list(payload)!r}"
            )
        payload = payload["products"]
    if not isinstance(payload, list):
        raise ValueError(f"Edu-V products endpoint must return a JSON list, got {type(payload).__name__}")
    return payload


def _collect_product_objects(
    page_rows: list[t.Any], start: int, on_invalid_row: t.Callable[[int, t.Any], None] | None
) -> list[JsonObject]:
    """Keep product objects and report invalid rows using their feed position."""
    objects: list[JsonObject] = []
    for index, row in enumerate(page_rows, start=start + 1):
        if isinstance(row, dict):
            objects.append(row)
        elif on_invalid_row:
            on_invalid_row(index, row)
        else:
            raise ValueError(f"Edu-V product row {index} must be an object, got {type(row).__name__}")
    return objects


def fetch_eduv_products(
    url: URL,
    uses_pagination: bool = False,
    timeout_seconds: float = 30.0,
    page_size: int = 100,
    on_page: t.Callable[[int, int, int], None] | None = None,
    on_invalid_row: t.Callable[[int, t.Any], None] | None = None,
) -> list[JsonObject]:
    """Fetch all product rows from an Edu-V endpoint."""
    if not uses_pagination:
        return _collect_product_objects(
            fetch_eduv_product_page(url, timeout_seconds=timeout_seconds), 0, on_invalid_row
        )

    rows: list[JsonObject] = []
    start = 0
    page_number = 0
    seen_page_start_ids: set[str] = set()
    while page_rows := fetch_eduv_product_page(
        url.update_query(start=start, limit=page_size),
        timeout_seconds=timeout_seconds,
    ):
        if page_number >= MAX_EDUV_PRODUCT_PAGES:
            raise ValueError(f"Edu-V feed exceeded the limit of {MAX_EDUV_PRODUCT_PAGES} pages")

        page_start_id = next(
            (
                row.get("productId")
                for row in page_rows
                if isinstance(row, dict) and isinstance(row.get("productId"), str)
            ),
            None,
        )
        if page_start_id is None or page_start_id in seen_page_start_ids:
            raise ValueError("Edu-V endpoint returned a repeated page or a page without a productId")

        seen_page_start_ids.add(page_start_id)
        rows.extend(_collect_product_objects(page_rows, start, on_invalid_row))
        page_number += 1
        if on_page:
            on_page(page_number, len(page_rows), start + len(page_rows))
        start += len(page_rows)
    return rows


class InvalidEduVProductRow(t.TypedDict):
    """Raw Edu-V product data plus validation and conversion errors."""

    _index: int
    _row: JsonObject
    _errors: list[str]
    _validation_errors: list[str]


class MinimalEduVProductEntity(BaseModel):
    """Validate only the identity needed for a rejected product row."""

    product_id: EduVProductID = Field(alias="productId")
    name: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    product_family_name: str | None = Field(default=None, alias="productFamilyName")


class ProductFieldTracker:
    """Record top-level Pydantic fields read during product conversion."""

    model_fields: t.ClassVar[dict[str, FieldInfo]]
    _used_fields: set[str] | None

    def __getattribute__(self, name: str) -> t.Any:
        """Track reads of generated product fields during conversion."""
        value = super().__getattribute__(name)
        if name in type(self).model_fields:
            used_fields = getattr(self, "_used_fields", None)
            if used_fields is not None:
                used_fields.add(name)
        return value


class TrackedEduVProductV1_1(ProductFieldTracker, catalogue_v1_1_0.Product):
    """Edu-V 1.1 product with field access tracking."""

    _used_fields: set[str] | None = PrivateAttr(default=None)


class TrackedEduVProductV2_0(ProductFieldTracker, catalogue_v2_0_0.Product):
    """Edu-V 2.0 product with field access tracking."""

    _used_fields: set[str] | None = PrivateAttr(default=None)


type TrackedEduVProduct = TrackedEduVProductV1_1 | TrackedEduVProductV2_0


class BaseEduVImporter(AbstractImporter, abc.ABC):
    """Shared Edu-V importer helpers for version-specific catalogue payloads."""

    base_url: str  # e.g. https://app.cumulus.co/api/edu-v/v1/ or
    # https://catalogus.edu-v.kennisnet.nl/v1/products?start=0&limit=100 with filter[publisher=Cumulus]
    supplier_gid: str | None = None
    endpoint_publisher: str | None = None
    endpoint_uses_pagination = False
    products_endpoint = "products"
    pagination_page_size = 100
    timeout_seconds = 30.0
    _products_cache: list[JsonObject] | None = None
    _logged_unused_product_models: set[str]

    max_eduv_version: str

    def __init__(
        self,
        base_url: str,
        supplier_gid: str | None = None,
        endpoint_publisher: str | None = None,
        endpoint_uses_pagination: bool = False,
        **_: t.Any,
    ) -> None:
        """Store connection settings for the Edu-V API."""
        super().__init__()
        self.base_url = base_url
        self._logged_unused_product_models = set()
        if supplier_gid:
            self.supplier_gid = supplier_gid

        if endpoint_publisher:
            self.endpoint_publisher = endpoint_publisher.strip()
        self.endpoint_uses_pagination = endpoint_uses_pagination

        self.warn_if_endpoint_version_is_newer()

    def warn_if_endpoint_version_is_newer(self) -> None:
        """Warn when the configured Edu-V endpoint advertises a newer version."""
        detected_version = self._extract_version_from_text(self.base_url)
        supported_version = self._extract_version_from_text(self.max_eduv_version)
        if not detected_version or not supported_version or detected_version <= supported_version:
            return

        self._warn_import(
            warning_code=ImportWarningCode.EDUV_NEWER_VERSION,
            message=f"Edu-V endpoint version {self._format_version(detected_version)} "
            f"is newer than supported {self.max_eduv_version}.",
        )

    def _fetch_products_payload(self) -> list[JsonObject]:
        if self._products_cache is not None:
            return self._products_cache

        if not self.base_url:
            raise ValueError(f"{self.__class__.__name__}.base_url is not configured")

        url = URL(self.base_url) / self.products_endpoint

        rows = fetch_eduv_products(
            url,
            uses_pagination=self.endpoint_uses_pagination,
            timeout_seconds=self.timeout_seconds,
            page_size=self.pagination_page_size,
            on_invalid_row=self._warn_nonobject_product_row,
        )

        if self.endpoint_publisher:
            for index, row in enumerate(rows, start=1):
                publisher = row.get("publisher")
                if not isinstance(publisher, str) or not publisher.strip():
                    self._warn_import(
                        warning_code=ImportWarningCode.EDUV_PRODUCT_ROW_SKIPPED,
                        message=f"Skipped Edu-V product row {index}: publisher is missing or invalid.",
                        reason=repr(row),
                    )
            rows = [row for row in rows if self._matches_endpoint_publisher(row)]

        self._products_cache = rows
        return rows

    def _warn_nonobject_product_row(self, index: int, row: t.Any) -> None:
        self._warn_import(
            warning_code=ImportWarningCode.EDUV_PRODUCT_ROW_SKIPPED,
            message=f"Skipped Edu-V product row {index}: expected an object, got {type(row).__name__}.",
            reason=repr(row),
        )

    def _matches_endpoint_publisher(self, row: JsonObject) -> bool:
        publisher = row.get("publisher")
        if not isinstance(publisher, str) or self.endpoint_publisher is None:
            return False
        return publisher.strip() == self.endpoint_publisher

    def _validate_products_payload[M: EduVProductModel](
        self,
        product_model: type[M],
    ) -> tuple[list[M], list[InvalidEduVProductRow]]:
        """Fetch and validate Edu-V product rows against the versioned schema."""
        validated_rows: list[M] = []
        invalid_rows: list[InvalidEduVProductRow] = []
        for index, row in enumerate(self._fetch_products_payload(), start=1):
            try:
                validated = product_model.model_validate(row)
            except ValidationError as exc:
                invalid_rows.append(
                    InvalidEduVProductRow(
                        _index=index,
                        _row=dict(row),
                        _errors=[ImportErrorCode.ROW_VALIDATION_FAILED],
                        _validation_errors=[
                            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()
                        ],
                    )
                )
                continue
            validated_rows.append(validated)
        return validated_rows, invalid_rows

    def _convert_products[M: TrackedEduVProduct](
        self, product_model: type[M]
    ) -> tuple[list[ImportProduct], list[InvalidEduVProductRow]]:
        validated_rows, invalid_rows = self._validate_products_payload(product_model)
        if invalid_rows:
            self._warn_import(
                warning_code=ImportWarningCode.EDUV_VALIDATION_FAILED,
                message=f"{len(invalid_rows)} Edu-V product rows failed schema validation.",
            )
        products = [self._convert_validated_product(product) for product in validated_rows]
        products.extend(self._convert_failing_product(row) for row in invalid_rows)
        return products, invalid_rows

    def _debug_unused_product_fields(self, product_model: type[EduVProductModel], used_fields: set[str]) -> None:
        model_name = product_model.__name__
        if model_name in self._logged_unused_product_models:
            return
        self._logged_unused_product_models.add(model_name)
        unused_fields = sorted(set(product_model.model_fields) - used_fields)
        if unused_fields:
            self._warn_import(
                warning_code=ImportWarningCode.EDUV_UNUSED_PRODUCT_FIELDS,
                message=f"{model_name} unused top-level fields: {', '.join(unused_fields)}",
            )

    def _convert_validated_product(self, product: TrackedEduVProduct) -> ImportProduct:
        product._used_fields = set()
        converted = self._build_import_product_from_validated_model(product)
        used_fields = product._used_fields or set()
        product._used_fields = None
        self._debug_unused_product_fields(
            type(product), used_fields | {"reseller", "date_created", "date_last_modified"}
        )
        return converted

    def _convert_failing_product(self, invalid: InvalidEduVProductRow) -> ImportProduct:
        supplier_gid = self.supplier_gid
        if supplier_gid is None:
            raise ValueError("Edu-V product import requires a supplier_gid")
        product_data: ImportProduct = {
            "supplier_gid": supplier_gid,
            "_errors": [ImportErrorCode.ROW_VALIDATION_FAILED],
        }
        try:
            identity = MinimalEduVProductEntity.model_validate(invalid["_row"])
        except ValidationError as exc:
            invalid["_validation_errors"].extend(
                f"identity.{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()
            )
        else:
            product_id = identity.product_id.root.root
            family_name = (identity.product_family_name or "").strip() or identity.name.strip()
            product_data.update(
                olid=olid.generate("product", product_id),
                name=identity.name,
                product_family_name=(identity.product_family_name or "").strip() or None,
                method_olid=olid.generate("method", self._method_key(identity.publisher, family_name)),
                method_name=family_name,
            )
            if self._looks_like_isbn(product_id):
                product_data["isbn"] = product_id
        product_data["_source_row"] = t.cast(dict[str, object], invalid["_row"])
        product_data["_source_row_index"] = invalid["_index"]
        product_data["_source_row_validation_errors"] = invalid["_validation_errors"]
        return product_data

    def _build_import_product_from_validated_model(self, product: EduVProductModel) -> ImportProduct:
        product_id = product.product_id.root.root
        level_names = [level.study_level_name for study in product.studies for level in study.study_levels or []]
        levels, level_x_year = self._split_levels_and_level_year(level_names, product_name=product.name)
        subjects = uniq(
            [
                *(subject.subject_name for subject in product.subjects),
                *(reference.title.casefold() for reference in product.course_references or [] if reference.title),
            ]
        )
        family_name = (product.product_family_name or "").strip() or product.name.strip()
        access_urls = []
        for entry in product.specific_access_urls or []:
            if entry.access_url.strip():
                access_urls.append(entry)
            else:
                self._warn_import(
                    warning_code=ImportWarningCode.EDUV_ACCESS_URL_SKIPPED,
                    message="Skipped Edu-V access URL entry with an empty URL.",
                    product_name=product.name,
                    reason=f"Access URL type: {entry.access_url_type.value}",
                )

        return t.cast(
            ImportProduct,
            {
                "supplier_gid": self.supplier_gid,
                "olid": olid.generate("product", product_id),
                "isbn": product_id if self._looks_like_isbn(product_id) else None,
                "name": product.name,
                "product_family_name": (product.product_family_name or "").strip() or None,
                "method_olid": olid.generate("method", self._method_key(product.publisher, family_name)),
                "method_name": family_name,
                "available": STATUS_MAPPING[product.status.value],
                "levels": levels,
                "level_x_year": level_x_year,
                "bouw": self._extract_bouw(level_x_year),
                "tto": self._is_tto(level_names),
                "subjects": subjects,
                "authors": self._extract_authors(product),
                "edition": self._extract_edition(product.edition),
                "publication_date": product.first_published_date,
                "image_url": self._extract_image_url(product),
                "description": product.long_description or product.short_description or None,
                "recommended_price": self._extract_recommended_price(product),
                "license_duration": self._extract_license_duration(product),
                "more_information": product.default_access_url or product.trial_access_url,
                "demo_environment_link": product.trial_access_url,
                "physical_digital_mix": self._extract_physical_digital_mix(product.type.value),
                "digital_folio_mix": [entry.value for entry in product.delivery_types or []],
                "bundle_product_olids": uniq(
                    olid.generate("product", ref.root.root) for ref in product.bundled_products or []
                ),
                "copyright_type": product.copyright_type.value,
                "deprecation_date": product.deprecation_date,
                "end_of_life_date": product.end_of_life_date,
                "follow_up_product_olid": (
                    olid.generate("product", product.follow_up_product.root.root) if product.follow_up_product else None
                ),
                "for_sale": product.for_sale,
                "intended_end_user_role": product.intended_end_user_role.value
                if product.intended_end_user_role
                else None,
                "is_consumption_product": product.is_consumption_product,
                "payment_models": [entry.value for entry in product.payment_models or []],
                "product_usages": [entry.value for entry in product.product_usages or []],
                "related_product_olids": uniq(
                    olid.generate("product", ref.root.root) for ref in product.related_products or []
                ),
                "sale_unit_size": product.sale_unit_size,
                "specific_access_urls": [entry.access_url.strip() for entry in access_urls],
                "specific_access_url_types": [entry.access_url_type.value for entry in access_urls],
                "supported_until_date": product.supported_until_date,
                "_errors": [],
            },
        )

    @staticmethod
    def _looks_like_isbn(value: str | None) -> bool:
        return bool(value and len(value) == 13 and value.isdigit())

    @staticmethod
    def _extract_version_from_text(value: str) -> tuple[int, int, int] | None:
        match = EDUV_VERSION_RE.search(value) or PLAIN_VERSION_RE.search(value)
        if not match:
            return None
        major, minor, patch = match.groups()
        return int(major or "0"), int(minor or "0"), int(patch or "0")

    @staticmethod
    def _format_version(version: tuple[int, int, int]) -> str:
        return ".".join(str(part) for part in version)

    def _split_levels_and_level_year(
        self, level_x_year: list[str], product_name: str | None = None
    ) -> tuple[list[str], list[str]]:
        levels: list[str] = []
        resolved_level_x_year: list[str] = []
        for value in level_x_year:
            match = None
            if isinstance(value, str):
                # TTO labels are a compatibility convention, not an official Edu-V study level format.
                normalized = TTO_LEVEL_RE.sub(" ", value).strip()
                match = LEVEL_YEAR_RE.fullmatch(normalized)
            if not match:
                self._warn_import(
                    warning_code=ImportWarningCode.EDUV_LEVEL_SKIPPED,
                    message=f"Skipped Edu-V study level {value!r}: expected a level label.",
                    product_name=product_name,
                    reason="Invalid level label",
                )
                continue
            level = "-".join(match.group("level").rstrip(",").casefold().split())
            if level in {"po", "groep"}:
                level = "PO"
            elif level not in CATALOG_LEVELS:
                self._warn_import(
                    warning_code=ImportWarningCode.EDUV_LEVEL_SKIPPED,
                    message=f"Skipped Edu-V study level {value!r}: no matching catalogue level.",
                    product_name=product_name,
                    reason=f"Unknown level {level!r}",
                )
                continue
            normalized_value = f"{level} {match.group('year')}" if match.group("year") else level
            if level not in levels:
                levels.append(level)
            if normalized_value not in resolved_level_x_year:
                resolved_level_x_year.append(normalized_value)
        return levels, resolved_level_x_year

    def _extract_authors(self, product: EduVProductModel) -> list[str]:
        if not product.authors:
            return []

        author_names: list[str] = []
        for individual in product.authors.individuals or []:
            full_name = " ".join(
                part
                for part in (
                    individual.given_name,
                    individual.family_name_prefix,
                    individual.family_name,
                )
                if part
            )
            if full_name and full_name not in author_names:
                author_names.append(full_name)

        for organisation in product.authors.organisations or []:
            if organisation and organisation not in author_names:
                author_names.append(organisation)

        return author_names

    def _extract_edition(self, edition: str | None) -> int | None:
        # todo: revisit this
        if not edition:
            return None

        digits: list[str] = []
        for char in edition:
            if char.isdigit():
                digits.append(char)
                continue
            if digits:
                break
        if not digits:
            return None
        return int("".join(digits))

    def _extract_image_url(self, product: EduVProductModel) -> str | None:
        media = product.media
        if media.main_thumbnail_url and media.main_thumbnail_url.url:
            return media.main_thumbnail_url.url
        if media.publisher_thumbnail_url.url:
            return media.publisher_thumbnail_url.url
        if media.product_image_urls:
            return media.product_image_urls[0].url
        return None

    def _extract_recommended_price(self, product: EduVProductModel) -> float | None:
        prices = product.price or []
        today = dt.date.today()
        current = [price for price in prices if price.valid_from <= today]
        if current:
            return max(current, key=lambda price: price.valid_from).price_incl
        future = [price for price in prices if price.valid_from > today]
        return min(future, key=lambda price: price.valid_from).price_incl if future else None

    def _extract_license_duration(self, product: EduVProductModel) -> str | None:
        if product.license_period:
            variant = product.license_period.license_variant.value
            days = product.license_period.license_days
            if variant == "days" and days:
                return f"{days} dagen"
            return variant
        if product.activation_period:
            return f"activation:{product.activation_period.activation_variant.value}"
        return None

    @staticmethod
    def _extract_physical_digital_mix(product_type: str) -> str | None:
        if product_type == "combi":
            return "mix"
        if product_type in {"physical", "digital"}:
            return product_type
        return None

    @staticmethod
    def _method_key(publisher_name: str, family_name: str) -> str:
        return f"{publisher_name.strip().lower()}:{family_name.strip().lower()}"

    @staticmethod
    def _extract_bouw(levels: list[str]) -> list[str]:
        result: set[str] = set()
        for level in levels:
            normalized = level.lower()
            if " " not in normalized:
                continue
            _, year_raw = normalized.rsplit(" ", 1)
            if not year_raw.isdigit():
                continue
            year = int(year_raw)
            result.add("bovenbouw" if year >= 4 else "onderbouw")
        return sorted(result)

    @staticmethod
    def _is_tto(levels: list[str]) -> bool:
        return any("tto" in level.lower() for level in levels)

    @staticmethod
    def _aggregate_publication_date(products: list[ImportProduct]) -> dt.date | None:
        publication_dates = [value for row in products if isinstance((value := row.get("publication_date")), dt.date)]
        return min(publication_dates) if publication_dates else None

    def _build_methods_from_products(self, products: list[ImportProduct]) -> list[ImportMethod]:
        grouped: dict[str, list[ImportProduct]] = defaultdict(list)
        for product in products:
            method_olid = product.get("method_olid")
            if isinstance(method_olid, str) and method_olid:
                grouped[method_olid].append(product)

        methods: list[ImportMethod] = []
        for method_olid, product_rows in grouped.items():
            valid_rows = [
                row for row in product_rows if ImportErrorCode.ROW_VALIDATION_FAILED not in row.get("_errors", [])
            ]
            if not valid_rows:
                first = product_rows[0]
                methods.append(
                    t.cast(
                        ImportMethod,
                        {
                            "name": first.get("method_name"),
                            "supplier_gid": first.get("supplier_gid"),
                            "olid": method_olid,
                            "_errors": [ImportErrorCode.ROW_VALIDATION_FAILED],
                        },
                    )
                )
                continue
            product_rows = valid_rows
            first = product_rows[0]

            levels = sorted(
                {
                    str(level)
                    for row in product_rows
                    for level in row.get("levels", [])
                    if isinstance(level, str) and level
                }
            )
            level_x_year = sorted(
                {
                    str(level)
                    for row in product_rows
                    for level in row.get("level_x_year", [])
                    if isinstance(level, str) and level
                }
            )
            subjects = sorted(
                {
                    str(subject)
                    for row in product_rows
                    for subject in row.get("subjects", [])
                    if isinstance(subject, str) and subject
                }
            )
            mixes = {mix for row in product_rows if (mix := row.get("physical_digital_mix"))}
            delivery_types = sorted(
                {
                    entry
                    for row in product_rows
                    for entry in row.get("digital_folio_mix", [])
                    if isinstance(entry, str) and entry
                }
            )

            physical_digital_mix = "mix" if len(mixes) > 1 else next(iter(mixes), "mix")
            method_name = first.get("method_name") or first.get("name")
            preview_digital_environment = next(
                (link for row in product_rows if (link := row.get("demo_environment_link"))),
                first.get("more_information"),
            )

            methods.append(
                t.cast(
                    ImportMethod,
                    {
                        "name": method_name,
                        "supplier_gid": first.get("supplier_gid"),
                        "olid": method_olid,
                        "available": first.get("available"),
                        "publication_date": self._aggregate_publication_date(product_rows),
                        "description": first.get("description"),
                        "levels": levels,
                        "subjects": subjects,
                        "image_url": first.get("image_url"),
                        "sample_copies": first.get("sample_copies_link") or first.get("more_information"),
                        "preview_digital_environment": preview_digital_environment,
                        "more_information": first.get("more_information"),
                        "physical_digital_mix": physical_digital_mix,
                        "digital_folio_mix": delivery_types,
                        "priority": max(int(row.get("priority") or 1) for row in product_rows),
                        "bouw": self._extract_bouw(level_x_year),
                        "tto": any(row.get("tto") for row in product_rows),
                    },
                )
            )

        return methods


class EduVImporterV1(BaseEduVImporter):
    """Import Edu-V catalogue data into the shared schema."""

    # https://edu-v.atlassian.net/wiki/spaces/AFSPRAKENS/pages/634421249/Catalogue+API

    source = "edu-v1-import"
    max_eduv_version = "1.1.0"

    @classmethod
    def from_env(
        cls,
        base_url: str,
        supplier_gid: str | None = None,
        endpoint_publisher: str | None = None,
    ) -> t.Self:
        """Build the v1 importer from its configured endpoint."""
        return cls(
            base_url=base_url,
            supplier_gid=supplier_gid,
            endpoint_publisher=endpoint_publisher,
        )

    def __init__(
        self,
        base_url: str,
        supplier_gid: str | None = None,
        endpoint_publisher: str | None = None,
        **extras: t.Any,
    ) -> None:
        """Initialize the v1 importer and emit endpoint-version warnings."""
        super().__init__(
            base_url=base_url,
            supplier_gid=supplier_gid,
            endpoint_publisher=endpoint_publisher,
            **extras,
        )

    def fetch_products(self) -> list[ImportProduct]:
        """Fetch, validate, and map Edu-V v1 products into import payloads."""
        products, _ = self._convert_products(TrackedEduVProductV1_1)
        return products

    def fetch_methods(self) -> list[ImportMethod]:
        """Derive method payloads from the fetched Edu-V v1 products."""
        return self._build_methods_from_products(self.fetch_products())


class EduVImporterV2(BaseEduVImporter):
    """Import Edu-V catalogue data into the shared schema."""

    source = "edu-v2-import"
    max_eduv_version = "2.0.0"

    @classmethod
    def from_env(
        cls,
        base_url: str,
        supplier_gid: str | None = None,
        endpoint_publisher: str | None = None,
    ) -> t.Self:
        """Build the v2 importer from its configured endpoint."""
        return cls(
            base_url=base_url,
            supplier_gid=supplier_gid,
            endpoint_publisher=endpoint_publisher,
        )

    def __init__(
        self,
        base_url: str,
        supplier_gid: str | None = None,
        endpoint_publisher: str | None = None,
        **extras: t.Any,
    ) -> None:
        """Initialize the v2 importer and emit endpoint-version warnings."""
        super().__init__(
            base_url=base_url,
            supplier_gid=supplier_gid,
            endpoint_publisher=endpoint_publisher,
            **extras,
        )

    def fetch_products(self) -> list[ImportProduct]:
        """Fetch, validate, and map Edu-V v2 products into import payloads."""
        products, _ = self._convert_products(TrackedEduVProductV2_0)
        return products

    def fetch_methods(self) -> list[ImportMethod]:
        """Derive method payloads from the fetched Edu-V v2 products."""
        return self._build_methods_from_products(self.fetch_products())


class EduVImporter(BaseEduVImporter):
    """Resolve and instantiate the matching Edu-V importer variant."""

    source = "edu-v-import"

    @classmethod
    def from_env(
        cls,
        base_url: str,
        supplier_gid: str | None = None,
        endpoint_publisher: str | None = None,
    ) -> BaseEduVImporter:
        """Build the version-matched importer from its configured endpoint."""
        return cls(
            base_url=base_url,
            supplier_gid=supplier_gid,
            endpoint_publisher=endpoint_publisher,
        )

    def __new__(
        cls,
        base_url: str,
        supplier_gid: str | None = None,
        endpoint_publisher: str | None = None,
        **extras: t.Any,
    ) -> BaseEduVImporter:
        """Instantiate and return the concrete importer for the endpoint version."""
        variant_class = cls._resolve_variant(base_url)
        return variant_class(
            base_url=base_url,
            supplier_gid=supplier_gid,
            endpoint_publisher=endpoint_publisher,
            **extras,
        )

    @staticmethod
    def _resolve_version(base_url: str) -> EduVFileVersion | None:
        base_url_lower = base_url.lower()
        if "/v1" in base_url_lower:
            return "v1"
        elif "/v2" in base_url_lower:
            return "v2"
        else:
            return None

    @staticmethod
    def _resolve_variant(base_url: str) -> type[BaseEduVImporter]:
        version = EduVImporter._resolve_version(base_url)
        if version == "v1":
            return EduVImporterV1
        elif version == "v2":
            return EduVImporterV2
        else:
            raise TypeError("Unsupported edu-v version.")
