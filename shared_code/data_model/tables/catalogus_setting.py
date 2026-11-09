"""Reusable global catalogue settings identified by a namespaced key."""

from typedal import TypedField
from typedal.fields import JSONField

from shared_code.data_model.tables.base import BaseTable


class CatalogusSetting(BaseTable):
    """One JSON setting with the standard GID and timestamp fields."""

    key = TypedField(str, length=120, label="Sleutel", notnull=True, unique=True)
    value = JSONField(label="Waarde", requires=[])
