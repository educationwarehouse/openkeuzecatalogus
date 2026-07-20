"""Base table definitions and shared fields."""

import typing as t
import uuid

from pydal import SQLCustomType
from typedal import TypeDAL, TypedTable
from typedal.fields import TypedField
from typedal.mixins import TimestampsMixin
from typedal.types import FieldSettings

from shared_code.data_model.mixins.markdown import MarkdownMixin
from shared_code.data_model.representers import dutch_date
from shared_code.data_model.validators.is_uuid import IS_UUID


# noinspection PyPep8Naming
def InternalUUIDField(**kw: t.Unpack[FieldSettings]) -> TypedField[str]:
    """Database type is uuid, Python type is str."""
    # variant of typedal NativeUUIDField that returns a str instead of UUID instance
    kw["type"] = SQLCustomType(
        type="string",
        native="uuid",
        encoder=lambda val: "" if val is None else str(val),
        # decoder=lambda value: value,
    )

    # fix `AttributeError: 'SQLCustomType' object has no attribute 'split'`:
    kw["type"].split = lambda on=None: str(kw["type"]).split(on)  # ty: ignore[unresolved-attribute]

    kw.setdefault("default", uuid.uuid4)
    kw.setdefault("writable", False)
    kw.setdefault("requires", IS_UUID())
    return TypedField(str, **kw)


class BaseTable(TypedTable, TimestampsMixin, MarkdownMixin):
    """Base table for all tables in the platform.

    Adds gid field, timestamps and markdown conversion to all tables.
    """

    gid = InternalUUIDField(label="Unieke Identifier")

    @classmethod
    def __on_define__(cls, db: TypeDAL) -> None:
        """Configure field representers when the table is defined."""
        super().__on_define__(db)

        # otherwise py4web will represent it with a `document.write()` in US format which is ugly and also breaks htmx
        cls.created_at.represent = dutch_date
        cls.updated_at.represent = dutch_date
