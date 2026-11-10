"""TypeDAL table definitions for applog persistence."""

from datetime import datetime

from typedal import relationship
from typedal.fields import TypedField

from shared_code.data_model.fields.uuid import OptionalUUIDField
from shared_code.data_model.tables.base import TableWithGid


class Evidence(TableWithGid):
    """Deduplicated applog event payload storage."""

    session_gid = OptionalUUIDField()
    source = TypedField(dict[str, object], type="json")
    sha1_digest = TypedField(str, length=40)


class Signal(TableWithGid):
    """Normalized applog signal events."""

    ts = TypedField(datetime, default=datetime.now)
    name = TypedField(str, required=True)
    source = TypedField(str, required=True, length=40)
    session_gid = OptionalUUIDField()
    user_gid = OptionalUUIDField()
    service_actor = TypedField(str | None, length=255)
    evidence_id = TypedField(int)
    evidence_gid = OptionalUUIDField()
    related = OptionalUUIDField()

    evidence = relationship(Evidence, lambda self, evidence: self.evidence_id == evidence.id)


class CountsPerMinute(TableWithGid):
    """Aggregated applog counts over minute buckets."""

    ts = TypedField(datetime, default=datetime.now)
    name = TypedField(str, required=True)
    evidence_id = TypedField(int)
    evidence_gid = OptionalUUIDField()
    count = TypedField(int)
