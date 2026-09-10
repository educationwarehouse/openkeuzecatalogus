"""Edu-V importer implementation."""

import abc
import datetime as dt
import re
import typing as t
from collections import defaultdict

import pydantic
from pydantic import ValidationError
from yayarl import URL

from shared_code.infra.http import fetch_json_payload
from shared_code.modules.scrapers.abs import AbstractImporter
from shared_code.modules.scrapers.eduv.generated import catalogue_v1_1_0, catalogue_v2_0_0
from shared_code.modules.scrapers.errors import ImportErrorCode
from shared_code.modules.scrapers.types import ImportMethod, ImportProduct, JsonObject
from shared_code.util import olid
from shared_code.util.lists import uniq

type EduVProductModel = pydantic.BaseModel
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


class InvalidEduVProductRow(t.TypedDict):
    """Raw Edu-V product data plus validation and conversion errors."""

    _index: int
    _row: JsonObject
    _errors: list[str]
    _validation_errors: list[str]


class BaseEduVImporter(AbstractImporter, abc.ABC):
    """Shared Edu-V importer helpers for version-specific catalogue payloads."""

    base_url: str  # e.g. https://app.cumulus.co/api/edu-v/v1/ or
    # https://catalogus.edu-v.kennisnet.nl/v1/products?start=0&limit=100 with filter[publisher=Cumulus]
    supplier_gid: str | None = None
    endpoint_publisher: str | None = None
    products_endpoint = "products"
    timeout_seconds = 30.0
    _products_cache: list[JsonObject] | None = None
    _logged_unused_product_models: set[str]

    max_eduv_version: str

    def __init__(
        self,
        base_url: str,
        supplier_gid: str | None = None,
        endpoint_publisher: str | None = None,
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

        self.warn_if_endpoint_version_is_newer()

    def warn_if_endpoint_version_is_newer(self) -> None:
        """Warn when the configured Edu-V endpoint advertises a newer version."""
        detected_version = self._extract_version_from_text(self.base_url)
        supported_version = self._extract_version_from_text(self.max_eduv_version)
        if not detected_version or not supported_version or detected_version <= supported_version:
            return

        self._warn_import(
            warning_code="eduv_newer_version",
            message=f"Edu-V endpoint version {self._format_version(detected_version)} "
            f"is newer than supported {self.max_eduv_version}.",
        )

    def _fetch_products_payload(self) -> list[JsonObject]:
        if self._products_cache is not None:
            return self._products_cache

        if not self.base_url:
            raise ValueError(f"{self.__class__.__name__}.base_url is not configured")

        url = URL(self.base_url) / self.products_endpoint

        payload = fetch_json_payload(
            url,
            timeout=self.timeout_seconds,
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

        if self.endpoint_publisher:
            rows = [row for row in rows if self._matches_endpoint_publisher(row)]

        self._products_cache = rows
        return rows

    def _matches_endpoint_publisher(self, row: JsonObject) -> bool:
        publisher = self._to_str(row.get("publisher"))
        if publisher is None or self.endpoint_publisher is None:
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

    def _debug_unused_product_fields(self, product_model: type[EduVProductModel], used_fields: set[str]) -> None:
        model_name = product_model.__name__
        if model_name in self._logged_unused_product_models:
            return
        self._logged_unused_product_models.add(model_name)
        unused_fields = sorted(set(product_model.model_fields) - used_fields)
        if unused_fields:
            self._warn_import(
                warning_code="eduv_unused_product_fields",
                message=f"{model_name} unused top-level fields: {', '.join(unused_fields)}",
            )

    def _convert_validated_product(self, product: EduVProductModel) -> ImportProduct:
        row = t.cast(JsonObject, product.model_dump(mode="python", by_alias=False, exclude_none=True))
        used_fields = set[str]()
        converted = self._build_import_product_from_normalized_row(row, used_fields)
        self._assign_method_metadata_from_normalized_row(converted, row, used_fields)
        self._debug_unused_product_fields(type(product), used_fields)
        return converted

    def _convert_failing_product(self, invalid: InvalidEduVProductRow) -> ImportProduct:
        product_data = self._build_import_product_from_raw_row(invalid["_row"])
        product_data["_errors"] = [ImportErrorCode.ROW_VALIDATION_FAILED]
        return product_data

    def _build_import_product_from_normalized_row(self, row: JsonObject, used_fields: set[str]) -> ImportProduct:
        product_id = self._extract_product_id(self._tracked_get(row, "product_id", used_fields))
        self._tracked_ignore(used_fields, "date_created", "date_last_modified", "reseller")
        level_x_year = self._extract_levels_from_normalized_studies(self._tracked_get(row, "studies", used_fields))
        levels, level_x_year = self._split_levels_and_level_year(level_x_year)

        long_description = self._to_str(self._tracked_get(row, "long_description", used_fields))
        short_description = self._to_str(self._tracked_get(row, "short_description", used_fields))

        default_access_url = self._to_str(self._tracked_get(row, "default_access_url", used_fields))
        trial_access_url = self._to_str(self._tracked_get(row, "trial_access_url", used_fields))
        subjects = uniq(
            [
                *self._extract_subjects_from_normalized(self._tracked_get(row, "subjects", used_fields)),
                *self._extract_subjects_from_course_references(
                    self._tracked_get(row, "course_references", used_fields)
                ),
            ]
        )

        specific_access_entries = self._extract_specific_access_urls(
            self._tracked_get(row, "specific_access_urls", used_fields)
        )

        return t.cast(
            ImportProduct,
            {
                "supplier_gid": self.supplier_gid,
                "olid": olid.generate("product", product_id) if product_id else None,
                "isbn": product_id if self._looks_like_isbn(product_id) else None,
                "name": self._to_str(self._tracked_get(row, "name", used_fields)) or None,
                "available": self._map_available(self._tracked_get(row, "status", used_fields)),
                "levels": levels,
                "level_x_year": level_x_year,
                "subjects": subjects,
                "authors": self._extract_authors_from_normalized(self._tracked_get(row, "authors", used_fields)),
                "edition": self._extract_edition_from_normalized(self._tracked_get(row, "edition", used_fields)),
                "publication_date": self._to_date(self._tracked_get(row, "first_published_date", used_fields)),
                "image_url": self._extract_image_url_from_normalized_media(
                    self._tracked_get(row, "media", used_fields)
                ),
                "description": long_description or short_description or None,
                "recommended_price": self._extract_recommended_price_from_normalized(
                    self._tracked_get(row, "price", used_fields),
                ),
                "license_duration": self._extract_license_duration_from_normalized(
                    self._tracked_get(row, "license_period", used_fields),
                    self._tracked_get(row, "activation_period", used_fields),
                ),
                "more_information": default_access_url or trial_access_url or None,
                "physical_digital_mix": self._extract_physical_digital_mix(self._tracked_get(row, "type", used_fields)),
                "digital_folio_mix": self._extract_delivery_types_from_normalized(
                    self._tracked_get(row, "delivery_types", used_fields)
                ),
                "bundle_product_olids": self._extract_product_reference_olids(
                    self._tracked_get(row, "bundled_products", used_fields)
                ),
                "copyright_type": self._to_str(self._tracked_get(row, "copyright_type", used_fields)) or None,
                "deprecation_date": self._to_date(self._tracked_get(row, "deprecation_date", used_fields)),
                "end_of_life_date": self._to_date(self._tracked_get(row, "end_of_life_date", used_fields)),
                "follow_up_product_olid": self._extract_product_reference_olid(
                    self._tracked_get(row, "follow_up_product", used_fields)
                ),
                "for_sale": self._to_bool(self._tracked_get(row, "for_sale", used_fields)),
                "intended_end_user_role": self._to_str(self._tracked_get(row, "intended_end_user_role", used_fields))
                or None,
                "is_consumption_product": self._extract_optional_bool(
                    self._tracked_get(row, "is_consumption_product", used_fields)
                ),
                "payment_models": self._extract_string_list(self._tracked_get(row, "payment_models", used_fields)),
                "product_usages": self._extract_string_list(self._tracked_get(row, "product_usages", used_fields)),
                "related_product_olids": self._extract_product_reference_olids(
                    self._tracked_get(row, "related_products", used_fields)
                ),
                "sale_unit_size": self._to_int(self._tracked_get(row, "sale_unit_size", used_fields)),
                "specific_access_urls": [entry["url"] for entry in specific_access_entries],
                "specific_access_url_types": [entry["type"] for entry in specific_access_entries],
                "supported_until_date": self._to_date(self._tracked_get(row, "supported_until_date", used_fields)),
                "_errors": [],
            },
        )

    @staticmethod
    def _tracked_get(row: JsonObject, field_name: str, used_fields: set[str]) -> t.Any:
        used_fields.add(field_name)
        return row.get(field_name)

    @staticmethod
    def _tracked_ignore(used_fields: set[str], *field_names: str) -> None:
        for field_name in field_names:
            used_fields.add(field_name)

    def _build_import_product_from_raw_row(self, row: JsonObject) -> ImportProduct:
        product_id = self._extract_product_id(row.get("productId"))
        level_x_year = self._extract_levels_from_raw_studies(row.get("studies"))
        levels, level_x_year = self._split_levels_and_level_year(level_x_year)
        subjects = uniq(
            [
                *self._extract_subjects_from_raw(row.get("subjects")),
                *self._extract_subjects_from_course_references(row.get("courseReferences")),
            ]
        )
        specific_access_entries = self._extract_specific_access_urls(row.get("specificAccessUrls"))
        return t.cast(
            ImportProduct,
            {
                "supplier_gid": self.supplier_gid,
                "olid": olid.generate("product", product_id) if product_id else None,
                "isbn": product_id if self._looks_like_isbn(product_id) else None,
                "name": self._to_str(row.get("name")) or None,
                "available": self._map_available(row.get("status")),
                "levels": levels,
                "level_x_year": level_x_year,
                "subjects": subjects,
                "publication_date": self._to_date(row.get("firstPublishedDate")),
                "image_url": self._extract_image_url_from_raw_media(row.get("media")),
                "description": self._to_str(row.get("longDescription"))
                or self._to_str(row.get("shortDescription"))
                or None,
                "recommended_price": self._extract_recommended_price_from_raw(row.get("price")),
                "license_duration": self._extract_license_duration_from_raw(
                    row.get("licensePeriod"),
                    row.get("activationPeriod"),
                ),
                "more_information": self._to_str(row.get("defaultAccessUrl"))
                or self._to_str(row.get("trialAccessUrl"))
                or None,
                "physical_digital_mix": self._extract_physical_digital_mix(row.get("type")),
                "bundle_product_olids": self._extract_product_reference_olids(row.get("bundledProducts")),
                "copyright_type": self._to_str(row.get("copyrightType")) or None,
                "deprecation_date": self._to_date(row.get("deprecationDate")),
                "end_of_life_date": self._to_date(row.get("endOfLifeDate")),
                "follow_up_product_olid": self._extract_product_reference_olid(row.get("followUpProduct")),
                "for_sale": self._to_bool(row.get("forSale")),
                "intended_end_user_role": self._to_str(row.get("intendedEndUserRole")) or None,
                "is_consumption_product": self._extract_optional_bool(row.get("isConsumptionProduct")),
                "payment_models": self._extract_string_list(row.get("paymentModels")),
                "product_usages": self._extract_string_list(row.get("productUsages")),
                "related_product_olids": self._extract_product_reference_olids(row.get("relatedProducts")),
                "sale_unit_size": self._to_int(row.get("saleUnitSize")),
                "specific_access_urls": [entry["url"] for entry in specific_access_entries],
                "specific_access_url_types": [entry["type"] for entry in specific_access_entries],
                "supported_until_date": self._to_date(row.get("supportedUntilDate")),
                "_errors": [],
            },
        )

    @staticmethod
    def _extract_product_id(value: t.Any) -> str | None:
        if isinstance(value, dict):
            root = value.get("root")
            if root is None:
                return None
            text = str(root).strip()
            return text or None
        text = str(value or "").strip()
        return text or None

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

    @staticmethod
    def _to_int(value: t.Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except TypeError, ValueError:
            return None

    def _extract_optional_bool(self, value: t.Any) -> bool | None:
        if value is None:
            return None
        return self._to_bool(value)

    def _extract_subjects_from_course_references(self, course_references: t.Any) -> list[str]:
        result: list[str] = []
        for reference in self._as_objects(course_references):
            title = self._to_str(reference.get("title"))
            if title and title not in result:
                result.append(title.casefold())
        return result

    def _extract_string_list(self, values: t.Any) -> list[str]:
        if not isinstance(values, list):
            return []
        result: list[str] = []
        for value in values:
            text = self._to_str(value)
            if text and text not in result:
                result.append(text)
        return result

    def _extract_product_reference_olid(self, value: t.Any) -> str | None:
        product_id = self._extract_product_id(value)
        if not product_id:
            return None
        return olid.generate("product", product_id)

    def _extract_product_reference_olids(self, values: t.Any) -> list[str]:
        if not isinstance(values, list):
            return []
        result: list[str] = []
        for value in values:
            product_olid = self._extract_product_reference_olid(value)
            if product_olid and product_olid not in result:
                result.append(product_olid)
        return result

    def _extract_specific_access_urls(self, values: t.Any) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for value in self._as_objects(values):
            access_url = self._to_str(value.get("access_url") if "access_url" in value else value.get("accessUrl"))
            access_type = self._to_str(
                value.get("access_url_type") if "access_url_type" in value else value.get("accessUrlType")
            )
            if access_url and access_type:
                result.append({"url": access_url, "type": access_type})
        return result

    @staticmethod
    def _map_available(status: t.Any) -> str:
        return STATUS_MAPPING.get(str(status or "").strip(), "onbekend")

    def _extract_levels_from_normalized_studies(self, studies: t.Any) -> list[str]:
        levels: list[str] = []
        for study in self._as_objects(studies):
            for study_level in self._as_objects(study.get("study_levels")):
                level_name = self._to_str(study_level.get("study_level_name"))
                if level_name and level_name not in levels:
                    levels.append(level_name)
        return levels

    def _extract_levels_from_raw_studies(self, studies: t.Any) -> list[str]:
        levels: list[str] = []
        for study in self._as_objects(studies):
            for study_level in self._as_objects(study.get("studyLevels")):
                level_name = self._to_str(study_level.get("studyLevelName"))
                if level_name and level_name not in levels:
                    levels.append(level_name)
        return levels

    @staticmethod
    def _split_levels_and_level_year(level_x_year: list[str]) -> tuple[list[str], list[str]]:
        resolved_level_x_year = uniq([level for level in level_x_year if isinstance(level, str) and level])
        levels = uniq([level.split(" ", 1)[0] for level in resolved_level_x_year])
        return levels, resolved_level_x_year

    def _extract_subjects_from_normalized(self, subjects: t.Any) -> list[str]:
        subject_names: list[str] = []
        for subject in self._as_objects(subjects):
            subject_name = self._to_str(subject.get("subject_name"))
            if subject_name and subject_name not in subject_names:
                subject_names.append(subject_name)
        return subject_names

    def _extract_subjects_from_raw(self, subjects: t.Any) -> list[str]:
        subject_names: list[str] = []
        for subject in self._as_objects(subjects):
            subject_name = self._to_str(subject.get("subjectName"))
            if subject_name and subject_name not in subject_names:
                subject_names.append(subject_name)
        return subject_names

    def _extract_authors_from_normalized(self, authors: t.Any) -> list[str]:
        if not isinstance(authors, dict):
            return []

        author_names: list[str] = []
        for individual in self._as_objects(authors.get("individuals")):
            full_name = " ".join(
                part
                for part in (
                    self._to_str(individual.get("given_name")),
                    self._to_str(individual.get("family_name_prefix")),
                    self._to_str(individual.get("family_name")),
                )
                if part
            )
            if full_name and full_name not in author_names:
                author_names.append(full_name)

        organisations = authors.get("organisations")
        if isinstance(organisations, list):
            for organisation in organisations:
                organisation_name = self._to_str(organisation)
                if organisation_name and organisation_name not in author_names:
                    author_names.append(organisation_name)

        return author_names

    def _extract_edition_from_normalized(self, edition: t.Any) -> int | None:
        # todo: revisit this
        text = self._to_str(edition)
        digits: list[str] = []
        for char in text:
            if char.isdigit():
                digits.append(char)
                continue
            if digits:
                break
        if not digits:
            return None
        return int("".join(digits))

    def _extract_delivery_types_from_normalized(self, delivery_types: t.Any) -> list[str]:
        if not isinstance(delivery_types, list):
            return []

        values: list[str] = []
        for delivery_type in delivery_types:
            value = self._to_str(delivery_type)
            if value and value not in values:
                values.append(value)
        return values

    def _extract_image_url_from_normalized_media(self, media: t.Any) -> str | None:
        if not isinstance(media, dict):
            return None
        for key in ("main_thumbnail_url", "publisher_thumbnail_url"):
            candidate = media.get(key)
            if isinstance(candidate, dict):
                url = self._to_str(candidate.get("url"))
                if url:
                    return url
        product_images = self._as_objects(media.get("product_image_urls"))
        if product_images:
            return self._to_str(product_images[0].get("url")) or None
        return None

    def _extract_image_url_from_raw_media(self, media: t.Any) -> str | None:
        if not isinstance(media, dict):
            return None
        for key in ("mainThumbnailUrl", "publisherThumbnailUrl"):
            candidate = media.get(key)
            if isinstance(candidate, dict):
                url = self._to_str(candidate.get("url"))
                if url:
                    return url
        product_images = self._as_objects(media.get("productImageUrls"))
        if product_images:
            return self._to_str(product_images[0].get("url")) or None
        return None

    def _extract_recommended_price_from_normalized(self, prices: t.Any) -> float | None:
        return self._select_recommended_price(prices, value_key="price_incl", valid_from_key="valid_from")

    def _extract_recommended_price_from_raw(self, prices: t.Any) -> float | None:
        return self._select_recommended_price(prices, value_key="priceIncl", valid_from_key="validFrom")

    def _select_recommended_price(self, prices: t.Any, *, value_key: str, valid_from_key: str) -> float | None:
        current_price: tuple[dt.date, float] | None = None
        future_price: tuple[dt.date, float] | None = None
        undated_price: float | None = None
        today = dt.date.today()

        for price in self._as_objects(prices):
            recommended_price = self._to_float(price.get(value_key))
            if recommended_price is None:
                continue

            valid_from = self._to_date(price.get(valid_from_key))
            if valid_from is None:
                if undated_price is None:
                    undated_price = recommended_price
                continue

            if valid_from <= today:
                if current_price is None or valid_from > current_price[0]:
                    current_price = (valid_from, recommended_price)
                continue

            if future_price is None or valid_from < future_price[0]:
                future_price = (valid_from, recommended_price)

        if current_price is not None:
            return current_price[1]
        if future_price is not None:
            return future_price[1]
        return undated_price

    @staticmethod
    def _to_date(value: t.Any) -> dt.date | None:
        if isinstance(value, dt.datetime):
            return value.date()
        if isinstance(value, dt.date):
            return value
        if not isinstance(value, str):
            return None
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            return None

    def _extract_license_duration_from_normalized(self, license_period: t.Any, activation_period: t.Any) -> str | None:
        if isinstance(license_period, dict):
            variant = self._to_str(license_period.get("license_variant"))
            days = license_period.get("license_days")
            if variant == "days" and days:
                return f"{days} dagen"
            if variant:
                return variant
        if isinstance(activation_period, dict):
            variant = self._to_str(activation_period.get("activation_variant"))
            if variant:
                return f"activation:{variant}"
        return None

    def _extract_license_duration_from_raw(self, license_period: t.Any, activation_period: t.Any) -> str | None:
        if isinstance(license_period, dict):
            variant = self._to_str(license_period.get("licenseVariant"))
            days = license_period.get("licenseDays")
            if variant == "days" and days:
                return f"{days} dagen"
            if variant:
                return variant
        if isinstance(activation_period, dict):
            variant = self._to_str(activation_period.get("activationVariant"))
            if variant:
                return f"activation:{variant}"
        return None

    @staticmethod
    def _extract_physical_digital_mix(product_type: t.Any) -> str | None:
        normalized_type = str(product_type or "").strip()
        if normalized_type == "combi":
            return "mix"
        if normalized_type in {"physical", "digital"}:
            return normalized_type
        return None

    @staticmethod
    def _method_key(publisher_name: str, family_name: str) -> str:
        return f"{publisher_name.lower()}:{family_name.lower()}"

    def _assign_method_metadata_from_normalized_row(
        self,
        product_data: ImportProduct,
        row: JsonObject,
        used_fields: set[str],
    ) -> None:
        publisher = self._to_str(self._tracked_get(row, "publisher", used_fields))
        family_name = self._to_str(self._tracked_get(row, "product_family_name", used_fields)) or self._to_str(
            self._tracked_get(row, "name", used_fields)
        )
        if not (publisher and family_name):
            return
        product_data["method_olid"] = olid.generate("method", self._method_key(publisher, family_name))
        product_data["method_name"] = family_name

    def _assign_method_metadata_from_raw_row(self, product_data: ImportProduct, row: JsonObject) -> None:
        publisher = self._to_str(row.get("publisher"))
        family_name = self._to_str(row.get("productFamilyName")) or self._to_str(row.get("name"))
        if not (publisher and family_name):
            return
        product_data["method_olid"] = olid.generate("method", self._method_key(publisher, family_name))
        product_data["method_name"] = family_name

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
            method_olid = self._to_str(product.get("method_olid"))
            if method_olid:
                grouped[method_olid].append(product)

        methods: list[ImportMethod] = []
        for method_olid, product_rows in grouped.items():
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
            mixes = {
                self._to_str(row.get("physical_digital_mix")) for row in product_rows if row.get("physical_digital_mix")
            }
            delivery_types = sorted(
                {
                    entry
                    for row in product_rows
                    for entry in row.get("digital_folio_mix", [])
                    if isinstance(entry, str) and entry
                }
            )

            physical_digital_mix = "mix" if len(mixes) > 1 else next(iter(mixes), "mix")
            method_name = self._to_str(first.get("method_name")) or self._to_str(first.get("name"))

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
                        "preview_digital_environment": first.get("more_information"),
                        "more_information": first.get("more_information"),
                        "physical_digital_mix": physical_digital_mix,
                        "digital_folio_mix": delivery_types,
                        "priority": max(int(row.get("priority") or 1) for row in product_rows),
                        "bouw": self._extract_bouw(level_x_year),
                        "tto": self._is_tto(levels),
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

    def convert_validated_product(self, product: catalogue_v1_1_0.Product) -> ImportProduct:
        """Convert a validated Edu-V v1 product into the shared import schema."""
        return self._convert_validated_product(product)

    def convert_failing_product(self, invalid: InvalidEduVProductRow) -> ImportProduct:
        """Convert an invalid Edu-V v1 row into the shared import schema."""
        return self._convert_failing_product(invalid)

    def fetch_products(self) -> list[ImportProduct]:
        """Fetch, validate, and map Edu-V v1 products into import payloads."""
        # 1. _fetch_products_payload + 2. try to load into the V1 pydantic class
        validated_rows, invalid_rows = self._validate_products_payload(catalogue_v1_1_0.Product)

        # Step 3, mapping validated Edu-V rows into shared import payloads
        validated_products: list[ImportProduct] = []
        for product in validated_rows:
            product_data = self.convert_validated_product(product)
            validated_products.append(product_data)

        invalid_products: list[ImportProduct] = []
        for failing_row in invalid_rows:
            product_data = self.convert_failing_product(failing_row)
            self._assign_method_metadata_from_raw_row(product_data, failing_row["_row"])
            invalid_products.append(product_data)

        return validated_products + invalid_products

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

    def convert_validated_product(self, product: catalogue_v2_0_0.Product) -> ImportProduct:
        """Convert a validated Edu-V v2 product into the shared import schema."""
        return self._convert_validated_product(product)

    def convert_failing_product(self, invalid: InvalidEduVProductRow) -> ImportProduct:
        """Convert an invalid Edu-V v2 row into the shared import schema."""
        return self._convert_failing_product(invalid)

    def fetch_products(self) -> list[ImportProduct]:
        """Fetch, validate, and map Edu-V v2 products into import payloads."""
        # 1. _fetch_products_payload + 2. try to load into the V2 pydantic class
        validated_rows, invalid_rows = self._validate_products_payload(catalogue_v2_0_0.Product)

        # Step 3, mapping validated Edu-V rows into shared import payloads
        validated_products: list[ImportProduct] = []
        for product in validated_rows:
            product_data = self.convert_validated_product(product)
            validated_products.append(product_data)

        invalid_products: list[ImportProduct] = []
        for failing_row in invalid_rows:
            product_data = self.convert_failing_product(failing_row)
            self._assign_method_metadata_from_raw_row(product_data, failing_row["_row"])
            invalid_products.append(product_data)

        return validated_products + invalid_products

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
