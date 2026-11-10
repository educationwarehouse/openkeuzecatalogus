"""TypeDAL table definitions for durable importer-run reporting."""

import typing as t
from datetime import datetime
from enum import StrEnum

from pydal.validators import IS_IN_SET
from typedal import relationship
from typedal.fields import TypedField

from shared_code.data_model.fields import OptionalUUIDField, UUIDReferenceField
from shared_code.data_model.tables.base import TableWithGid

# todo: docs about these tables + fields


class KennisnetCoverageStatus(StrEnum):
    """How a Kennisnet publisher is covered by the local catalogue."""

    IMPORTED = "imported"
    OWN_ENDPOINT = "own_endpoint"
    UNCONFIGURED = "unconfigured"
    UNKNOWN = "unknown"


KENNISNET_COVERAGE_STATUS_LABELS = {
    KennisnetCoverageStatus.IMPORTED: "Geïmporteerd via Kennisnet",
    KennisnetCoverageStatus.OWN_ENDPOINT: "Eigen Edu-V endpoint",
    KennisnetCoverageStatus.UNCONFIGURED: "Bekend, endpoint niet ingesteld",
    KennisnetCoverageStatus.UNKNOWN: "Onbekende leverancier",
}

type ImporterRunPhase = t.Literal["queued", "importing", "images", "completed", "failed"]
IMPORTER_RUN_PHASES = t.get_args(ImporterRunPhase)


class ImporterRun(TableWithGid):
    """One importer run, from start through its final outcome."""

    source = TypedField(str, required=True, length=80)
    endpoint_type = TypedField(str, length=40)
    supplier_gid = OptionalUUIDField()
    supplier_name = TypedField(str, length=255)
    job_key = TypedField(str, unique=True, length=255)
    started_at = TypedField(datetime, required=True)
    finished_at = TypedField(datetime)
    duration_ms = TypedField(int, default=0)
    success = TypedField(bool)
    phase = TypedField(
        str,
        required=True,
        default="completed",
        length=40,
        requires=IS_IN_SET(IMPORTER_RUN_PHASES),
    )
    failure_message = TypedField(str)
    payload_json = TypedField(dict[str, object], type="json")

    events = relationship(
        list["ImporterRunEvent"],
        condition=lambda run, event: event.run_gid == run.gid,
        join="left",
    )
    warnings = relationship(
        list["ImporterRunEvent"],
        condition=lambda run, event: (event.run_gid == run.gid) & (event.event_type == "warning"),
        join="left",
        lazy="allow",
    )

    @property
    def warnings_json(self) -> list[dict[str, object]]:
        """Render warning events, using the joined relationship when preloaded."""
        return [
            (warning.details or {})
            | {
                "warning_code": warning.metric,
                "product_name": (warning.details or {}).get("product_name") or warning.entity_name,
                "supplier_gid": warning.supplier_gid,
                "supplier_name": warning.supplier_name,
                "entity_type": warning.entity_type,
                "entity_gid": warning.entity_gid,
                "entity_olid": warning.entity_olid,
            }
            for warning in sorted(self.warnings, key=lambda event: event.id)
        ]


class ImporterRunEvent(TableWithGid):
    """One durable importer-run reporting event."""

    run_gid = UUIDReferenceField(required=True)
    supplier_gid = OptionalUUIDField()
    supplier_name = TypedField(str, length=255)
    event_type = TypedField(str, required=True, length=40)
    scope_type = TypedField(str, length=40)
    scope_key = TypedField(str, length=255)
    scope_label = TypedField(str, length=255)
    metric = TypedField(str, required=True, length=80)
    entity_type = TypedField(str, required=True, length=20)
    entity_gid = OptionalUUIDField()
    entity_olid = TypedField(str, length=255)
    entity_name = TypedField(str, length=255)
    value = TypedField(int)
    details = TypedField(dict[str, object], type="json")
