"""Typed payload and statistics helpers for scraper imports."""

import dataclasses as dc
import enum
import typing as t

from shared_code.generated.import_payloads import ImportMethod, ImportProduct, ImportSupplier, ImportVision

JsonPrimitive = str | int | float | bool | None
JsonValue = JsonPrimitive | dict[str, "JsonValue"] | list["JsonValue"]
JsonObject = dict[str, JsonValue]

# status offsets (outside enum)
OFFSET_ERR = 10
OFFSET_OK = 20

# spacing strategy
SOURCE_STRIDE = 100
SUPPLIER_BAND = 10_000
GRIST_BASE = 90_000
HUMAN_BASE = 100_000

# source bases (outside enum)
GENERIC_IMPORTER_BASE = SUPPLIER_BAND + 0 * SOURCE_STRIDE
CUMULUS_BASE = SUPPLIER_BAND + 1 * SOURCE_STRIDE

# todo: this is an example prio implementation,
#       later we might want to differentiate multiple error types etc.


class ImportPriority(enum.IntEnum):
    """Priority buckets used to separate importer and human-written rows."""

    IMPORTER_ERR = GENERIC_IMPORTER_BASE + OFFSET_ERR
    IMPORTER_OK = GENERIC_IMPORTER_BASE + OFFSET_OK

    HUMAN_OK = HUMAN_BASE + OFFSET_OK

    @classmethod
    def normalize(cls, prio: int | t.Self) -> int:
        """Normalize importer priority to a validated positive integer."""
        resolved_prio = int(prio)
        if resolved_prio <= 0:
            raise ValueError(f"Importer priority must be > 0, got {resolved_prio}")
        return resolved_prio

    @classmethod
    def is_ok(cls, prio: int | t.Self) -> bool:
        """Return whether a priority is in the OK bucket."""
        return int(prio) % SOURCE_STRIDE == OFFSET_OK

    @classmethod
    def is_err(cls, prio: int | t.Self) -> bool:
        """Return whether a priority is in the error bucket."""
        return int(prio) % SOURCE_STRIDE == OFFSET_ERR

    @classmethod
    def is_human(cls, prio: int | t.Self) -> bool:
        """Return whether a priority comes from human-written data."""
        return int(prio) >= HUMAN_BASE


@dc.dataclass
class ImportTypeStats:
    """Counts seen/new/changed/skipped/removed rows for one entity type."""

    seen: int = 0
    new: int = 0
    changed: int = 0
    skipped: int = 0
    removed: int = 0
    issues: int = 0


@dc.dataclass
class ImportRunErrorStat:
    """One importer error row stored with a run."""

    entity_type: str
    error_code: str
    supplier_gid: str | None = None
    supplier_name: str | None = None
    entity_gid: str | None = None
    entity_olid: str | None = None
    entity_name: str | None = None
    method_gid: str | None = None
    method_name: str | None = None
    validation_failed: bool = False
    error_details: JsonObject | None = None


@dc.dataclass
class ImportRunCountStat:
    """One named count stored with a run."""

    count_type: str
    count_key: str
    metric: str
    value: int
    supplier_gid: str | None = None
    supplier_name: str | None = None
    count_label: str | None = None


@dc.dataclass
class ImportRunWarningStat:
    """One importer warning stored with a run."""

    warning_code: str
    message: str


@dc.dataclass
class ImportAuxStats:
    """Minimal importer stats for entities that do not use full change buckets.

    `ImportTypeStats` is for flows that distinguish `new`, `changed`,
    `skipped`, `removed`, and `issues` and then export those per-metric counts
    into run reporting. Suppliers and visions currently do not report at that
    level. They only track how many rows were seen, how many resulted in a
    persisted import action, and how many failed validation, so they use this
    narrower shape instead.
    """

    seen: int = 0
    imported: int = 0
    issues: int = 0


@dc.dataclass
class CdnImageUploadStats:
    """Counts storage operations while mirroring product images to the CDN."""

    attempted: int = 0
    uploaded: int = 0
    failed: int = 0
    skipped: int = 0


@dc.dataclass
class ChangeResult:
    """Result of comparing an incoming row against stored data."""

    status: ChangeStatus
    validation_errors: dict[str, str] = dc.field(default_factory=dict)


@dc.dataclass
class ImportStats:
    """All counters and run-log facts collected during one import."""

    methods: ImportTypeStats = dc.field(default_factory=ImportTypeStats)
    products: ImportTypeStats = dc.field(default_factory=ImportTypeStats)
    suppliers: ImportAuxStats = dc.field(default_factory=ImportAuxStats)
    visions: ImportAuxStats = dc.field(default_factory=ImportAuxStats)
    image_uploads: CdnImageUploadStats = dc.field(default_factory=CdnImageUploadStats)
    error_stats: list[ImportRunErrorStat] = dc.field(default_factory=list)
    warning_stats: list[ImportRunWarningStat] = dc.field(default_factory=list)
    count_stats: list[ImportRunCountStat] = dc.field(default_factory=list)

    def _iter_rows(self) -> list[tuple[str, ImportTypeStats]]:
        rows: list[tuple[str, ImportTypeStats]] = []
        for field in dc.fields(self):
            value = getattr(self, field.name)
            if isinstance(value, ImportTypeStats):
                type_name = field.name.removesuffix("s")
                rows.append((type_name, value))
        return rows

    def __repr__(self) -> str:
        """Render the import stats as a compact text table."""
        headers = ("type", "seen", "new", "changed", "issues", "removed")
        rows = sorted(self._iter_rows(), key=lambda row: row[0])

        if not rows:
            return "ImportStats (no rows)"

        table_rows = [
            (
                name,
                str(stats.seen),
                str(stats.new),
                str(stats.changed),
                str(stats.issues),
                str(stats.removed),
            )
            for name, stats in rows
        ]

        widths = [len(h) for h in headers]
        for row in table_rows:
            for idx, value in enumerate(row):
                widths[idx] = max(widths[idx], len(value))

        def fmt(values: tuple[str, ...]) -> str:
            return " | ".join(value.ljust(widths[idx]) for idx, value in enumerate(values))

        separator = "-+-".join("-" * width for width in widths)
        lines = [fmt(headers), separator, *[fmt(row) for row in table_rows]]
        return "ImportStats\n" + "\n".join(lines)


class ChangeStatus(enum.Enum):
    """High-level outcomes of an import row comparison."""

    UNCHANGED = "unchanged"
    NEW = "new"
    CHANGED = "changed"
    INVALID = "invalid"


def to_err_prio(prio: int | ImportPriority) -> int:
    """Convert a normal priority into the matching error priority bucket."""
    resolved_prio = ImportPriority.normalize(prio)
    if ImportPriority.is_ok(resolved_prio):
        return resolved_prio - OFFSET_OK + OFFSET_ERR
    return resolved_prio


__all__ = [
    "CUMULUS_BASE",
    "GENERIC_IMPORTER_BASE",
    "GRIST_BASE",
    "HUMAN_BASE",
    "OFFSET_ERR",
    "OFFSET_OK",
    "SOURCE_STRIDE",
    "SUPPLIER_BAND",
    "CdnImageUploadStats",
    "ChangeResult",
    "ChangeStatus",
    "ImportAuxStats",
    "ImportMethod",
    "ImportPriority",
    "ImportProduct",
    "ImportRunCountStat",
    "ImportRunErrorStat",
    "ImportRunWarningStat",
    "ImportStats",
    "ImportSupplier",
    "ImportTypeStats",
    "ImportVision",
    "JsonObject",
    "JsonPrimitive",
    "JsonValue",
    "to_err_prio",
]
