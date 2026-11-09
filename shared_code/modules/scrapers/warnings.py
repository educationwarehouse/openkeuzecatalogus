"""Typed warning payloads and adapters for durable importer-run reporting."""

import typing as t

from shared_code.data_model import ImporterRun, ImporterRunEvent
from shared_code.modules.scrapers.types import ImportRunWarningStat


class ImportWarningDetails(t.TypedDict):
    """Diagnostic context stored in a warning event's details."""

    message: str
    product_name: str | None
    reason: str | None
    source_url: str | None


def warning_details(warning: ImportRunWarningStat) -> ImportWarningDetails:
    """Keep diagnostic text separate from searchable event identity."""
    return ImportWarningDetails(
        message=warning.message,
        product_name=warning.product_name,
        reason=warning.reason,
        source_url=warning.source_url,
    )


def has_import_warnings(run: ImporterRun) -> bool:
    """Check warning presence without loading diagnostic payloads."""
    return ImporterRunEvent.where(run_gid=run.gid, event_type="warning").exists()
