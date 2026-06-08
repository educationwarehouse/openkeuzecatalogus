"""TypeDAL table definitions for applog persistence."""

import typing as t
import uuid
from datetime import datetime

from typedal import TypedTable
from typedal.fields import TypedField, UUIDField


class Evidence(TypedTable):
    """Deduplicated applog event payload storage."""

    gid = UUIDField(default=uuid.uuid4, writable=False, filter_out=str)
    session_gid = UUIDField(filter_out=str)
    source = TypedField(dict[str, t.Any], type="json")
    sha1_digest = TypedField(str, length=40)


class Signal(TypedTable):
    """Normalized applog signal events."""

    gid = UUIDField(default=uuid.uuid4, writable=False, filter_out=str)
    ts = TypedField(datetime, default=datetime.now)
    name = TypedField(str, required=True)
    source = TypedField(str, required=True, length=40)
    session_gid = UUIDField(filter_out=str)
    user_gid = UUIDField(filter_out=str)
    evidence_id = TypedField(int)
    evidence_gid = UUIDField(filter_out=str)
    related = UUIDField(filter_out=str)


class CountsPerMinute(TypedTable):
    """Aggregated applog counts over minute buckets."""

    gid = UUIDField(default=uuid.uuid4, writable=False, filter_out=str)
    ts = TypedField(datetime, default=datetime.now)
    name = TypedField(str, required=True)
    evidence_id = TypedField(int)
    evidence_gid = UUIDField(filter_out=str)
    count = TypedField(int)
