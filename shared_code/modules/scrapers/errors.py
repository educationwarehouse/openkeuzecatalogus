"""Import error codes and helpers for normalizing scraper failures."""

import enum
import typing as t


class ImportErrorCode(enum.StrEnum):
    """Supported error codes emitted by scraper imports."""

    STATUS_UNKNOWN = "status_unknown"
    LEVELS_PARSE_FAILED = "levels_parse_failed"
    BOUW_PARSE_FAILED = "bouw_parse_failed"
    METHOD_LINK_MISSING = "method_link_missing"
    LICENSE_ACTIVATION_MISSING = "license_activation_missing"
    ROW_VALIDATION_FAILED = "row_validation_failed"

    @property
    def label_nl(self) -> str:
        """Return the Dutch display label for the error code."""
        return {
            ImportErrorCode.STATUS_UNKNOWN: "Onbekende status",
            ImportErrorCode.LEVELS_PARSE_FAILED: "Niveaus niet te parsen",
            ImportErrorCode.BOUW_PARSE_FAILED: "Bouw niet te bepalen",
            ImportErrorCode.METHOD_LINK_MISSING: "Geen methodelink",
            ImportErrorCode.LICENSE_ACTIVATION_MISSING: "Licentie/activatie ontbreekt",
            ImportErrorCode.ROW_VALIDATION_FAILED: "Validatie mislukt",
        }.get(self, str(self))

    @classmethod
    def from_value(cls, raw_code: str | None) -> ImportErrorCode | None:
        """Parse a raw string into a known error code, if possible."""
        if raw_code is None:
            return None
        code = str(raw_code).strip()
        if not code:
            return None
        try:
            return cls(code)
        except ValueError:
            return None


def normalize_import_error_codes(raw_codes: t.Iterable[str | ImportErrorCode] | None) -> list[str]:
    """Normalize raw error inputs into a deduplicated list of code strings."""
    if raw_codes is None:
        return []

    values: list[str | ImportErrorCode] = (
        [raw_codes] if isinstance(raw_codes, (str, ImportErrorCode)) else list(raw_codes)
    )

    deduplicated: list[str] = []
    for raw_code in values:
        import_error = ImportErrorCode.from_value(str(raw_code))
        code = import_error.value if import_error else str(raw_code or "").strip()
        if code and code not in deduplicated:
            deduplicated.append(code)
    return deduplicated
