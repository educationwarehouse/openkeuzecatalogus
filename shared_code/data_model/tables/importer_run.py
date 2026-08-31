"""TypeDAL table definitions for durable importer-run reporting."""

import typing as t
import uuid
from datetime import datetime

from typedal import TypedTable, relationship
from typedal.fields import TypedField, UUIDField


class ImporterRun(TypedTable):
    """One finished importer run."""

    gid = UUIDField(default=uuid.uuid4, writable=False, filter_out=str)
    source = TypedField(str, required=True, length=80)
    endpoint_type = TypedField(str, length=40)
    supplier_gid = UUIDField(filter_out=str)
    supplier_name = TypedField(str, length=255)
    job_key = TypedField(str, unique=True, length=255)
    started_at = TypedField(datetime, required=True)
    finished_at = TypedField(datetime, required=True)
    duration_ms = TypedField(int, default=0)
    success = TypedField(bool, required=True, default=True)
    failure_message = TypedField(str)
    payload_json = TypedField(dict[str, t.Any], type="json")
    warnings_json = TypedField(list[dict[str, str]], type="json")
    error_stats = relationship(
        list["ImporterRunErrorStat"],
        condition=lambda run, error_stat: error_stat.run_gid == run.gid,
        join="left",
    )


class ImporterRunCountStat(TypedTable):
    """Generic per-run count facts for reporting."""

    gid = UUIDField(default=uuid.uuid4, writable=False, filter_out=str)
    run_gid = UUIDField(filter_out=str, required=True)
    supplier_gid = UUIDField(filter_out=str)
    supplier_name = TypedField(str, length=255)
    count_type = TypedField(str, required=True, length=40)
    count_key = TypedField(str, required=True, length=255)
    count_label = TypedField(str, length=255)
    metric = TypedField(str, required=True, length=40)
    value = TypedField(int, required=True, default=0)


class ImporterRunErrorStat(TypedTable):
    """Per-run row-level importer error facts."""

    gid = UUIDField(default=uuid.uuid4, writable=False, filter_out=str)
    run_gid = UUIDField(filter_out=str, required=True)
    supplier_gid = UUIDField(filter_out=str)
    supplier_name = TypedField(str, length=255)
    entity_type = TypedField(str, required=True, length=20)
    entity_gid = UUIDField(filter_out=str)
    entity_olid = TypedField(str, length=255)
    entity_name = TypedField(str, length=255)
    method_gid = UUIDField(filter_out=str)
    method_name = TypedField(str, length=255)
    error_code = TypedField(str, required=True, length=80)
    validation_failed = TypedField(bool, required=True, default=False)
    error_details = TypedField(dict[str, t.Any], type="json")
