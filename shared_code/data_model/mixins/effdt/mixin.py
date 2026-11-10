"""Effective-dating related fields shared across multiple tables."""

from typedal import TypeDAL
from typedal.fields import BooleanField, StringField, TimestampField, TypedField
from typedal.mixins import Mixin

from shared_code.data_model.fields import OptionalUUIDField
from shared_code.data_model.representers import dutch_date, fix_sqlcustomtype
from shared_code.util.time import utcnow


class EffdtFields(Mixin):
    """Mixin that adds effective-dating and synchronization metadata fields."""

    effdt = TimestampField(
        readable=True,
        writable=False,
        default=utcnow,
        label="Laatst bijgewerkt",
        represent=dutch_date,
    )
    effstatus = BooleanField(default=True, writable=False)
    last_saved_by = StringField(writable=False, label="Laatst Bijgewerkt Door")
    prio = TypedField(int, default=0, writable=False, readable=False)
    sync_gid = OptionalUUIDField(writable=False, readable=False)  # default = uuid7 via psql

    @classmethod
    def __on_define__(cls, db: TypeDAL) -> None:
        """Apply post-definition fixes for custom SQL field representations."""
        super().__on_define__(db)

        fix_sqlcustomtype(cls.sync_gid)
        fix_sqlcustomtype(cls.effdt)
