"""Edu-V catalogue imports backed by an uploaded JSON document."""

import typing as t
from dataclasses import dataclass

from shared_code.data_model import AnyDict
from shared_code.modules.scrapers.eduv import (
    BaseEduVImporter,
    EduVFileVersion,
    EduVImporter,
    InvalidEduVProductRow,
    TrackedEduVProductV1_1,
    TrackedEduVProductV2_0,
)
from shared_code.modules.scrapers.errors import ImportWarningCode
from shared_code.modules.scrapers.types import (
    ImportMethod,
    ImportPriority,
    ImportProduct,
    ImportStats,
    JsonObject,
    JsonValue,
)


@dataclass(frozen=True)
class EduVFileValidationError:
    """One invalid Edu-V product row shown before a file import can continue."""

    index: int
    messages: list[str]
    source_row: JsonObject


class EduVPayloadImporter(BaseEduVImporter):
    """Run the regular Edu-V normalization flow against an in-memory document."""

    source = "edu-v-payload-import"
    max_eduv_version = "2.0.0"

    def __init__(
        self,
        payload: JsonValue | AnyDict,
        version: EduVFileVersion,
        supplier_gid: str,
        endpoint_publisher: str | None = None,
        **extras: t.Any,
    ) -> None:
        """Initialize an importer for an in-memory Edu-V catalogue payload.

        Args:
            payload: JSON payload containing products to validate and import.
            version: Edu-V schema version used to validate the payload.
            supplier_gid: Global identifier of the supplier owning the products.
            endpoint_publisher: Optional publisher value used to filter products.
            **extras: Additional options passed to the base importer.

        """
        self.payload = payload
        self.version = version
        self._converted_products: list[ImportProduct] | None = None
        self._validation_errors: list[EduVFileValidationError] = []
        super().__init__(
            base_url=f"https://uploaded-file.invalid/{version}",
            supplier_gid=supplier_gid,
            endpoint_publisher=endpoint_publisher,
            **extras,
        )

    @classmethod
    def from_env(
        cls,
        payload: JsonValue,
        version: EduVFileVersion,
        supplier_gid: str,
        endpoint_publisher: str | None = None,
    ) -> t.Self:
        """Build the importer from a supplied document, not an endpoint URL."""
        return cls(
            payload=payload,
            version=version,
            supplier_gid=supplier_gid,
            endpoint_publisher=endpoint_publisher,
        )

    def _payload_rows(self) -> list[JsonValue]:
        """Resolve and validate the product collection in an uploaded document."""
        if isinstance(self.payload, list):
            payload_rows = self.payload
        elif isinstance(self.payload, dict):
            missing = object()
            payload_rows = next(
                (self.payload[key] for key in ("products", "items", "results", "data") if key in self.payload),
                missing,
            )
            if payload_rows is missing:
                raise ValueError("Edu-V payload has no product collection")
        else:
            raise ValueError("Edu-V payload must be a product list or an object containing one")

        if not isinstance(payload_rows, list):
            raise ValueError("Edu-V product collection must be a list")
        return payload_rows

    def _fetch_products_payload(self) -> list[JsonObject]:
        """Read product objects from the uploaded payload without fetching an endpoint."""
        if self._products_cache is not None:
            return self._products_cache

        rows: list[JsonObject] = []
        for index, row in enumerate(self._payload_rows(), start=1):
            if isinstance(row, dict):
                publisher = row.get("publisher")
                if self.endpoint_publisher and (not isinstance(publisher, str) or not publisher.strip()):
                    self._warn_import(
                        warning_code=ImportWarningCode.EDUV_PRODUCT_ROW_SKIPPED,
                        message=f"Skipped Edu-V product row {index}: publisher is missing or invalid.",
                        reason=repr(row),
                    )
                rows.append(row)
            else:
                self._warn_nonobject_product_row(index, row)

        if self.endpoint_publisher:
            rows = [row for row in rows if self._matches_endpoint_publisher(row)]
        self._products_cache = rows
        return rows

    def validation_errors(self) -> list[EduVFileValidationError]:
        """Return all schema and conversion errors found in the uploaded rows."""
        self.fetch_products()
        return self._validation_errors

    def fetch_products(self) -> list[ImportProduct]:
        """Validate and normalize products using the selected Edu-V schema."""
        if self._converted_products is not None:
            return self._converted_products

        product_model = TrackedEduVProductV1_1 if self.version == "v1" else TrackedEduVProductV2_0
        products, invalid_rows = self._convert_products(product_model)
        self._validation_errors.extend(self._invalid_row_errors(invalid_rows))
        self._converted_products = products
        return products

    def fetch_methods(self) -> list[ImportMethod]:
        """Derive methods from the validated, normalized product list."""
        return self._build_methods_from_products(self.fetch_products())

    def import_methods_and_products(
        self,
        *,
        prio: int | ImportPriority,
        last_saved_by: str,
        mark_removed: bool = True,
    ) -> ImportStats:
        """Limit optional removal marking to the supplier owning this file."""
        return self.flow.import_methods_and_products(
            methods=self.fetch_methods(),
            products=self.fetch_products(),
            prio=prio,
            last_saved_by=last_saved_by,
            mark_removed=mark_removed,
            removed_supplier_gid=self.supplier_gid,
        )

    @staticmethod
    def _invalid_row_errors(rows: list[InvalidEduVProductRow]) -> list[EduVFileValidationError]:
        """Translate Pydantic validation failures for the admin preview."""
        return [
            EduVFileValidationError(
                index=row["_index"],
                messages=list(row["_validation_errors"]),
                source_row=row["_row"],
            )
            for row in rows
        ]


class EduVFileImporter(EduVPayloadImporter):
    """Run the in-memory Edu-V flow for an uploaded document."""

    source = "edu-v-file-import"


def default_eduv_file_version(endpoint_base_url: str | None) -> EduVFileVersion | None:
    """Derive the upload-form default from the supplier's configured endpoint."""
    return EduVImporter._resolve_version(endpoint_base_url or "")


__all__ = [
    "EduVFileImporter",
    "EduVFileValidationError",
    "EduVFileVersion",
    "EduVPayloadImporter",
    "default_eduv_file_version",
]
