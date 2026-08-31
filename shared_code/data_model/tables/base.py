"""Shared base table definition for the project's data model tables."""

from typedal import TypeDAL, TypedTable
from typedal.mixins import TimestampsMixin

from shared_code.data_model.fields import InternalUUIDField
from shared_code.data_model.mixins.markdown import MarkdownMixin
from shared_code.data_model.representers import dutch_date


class TableWithGid(TypedTable):
    """Base table for almost all tables in the platform, simply adds a gid field."""

    gid = InternalUUIDField(label="Unieke Identifier")


class BaseTable(TableWithGid, TimestampsMixin, MarkdownMixin):
    """Base table for most tables in the platform.

    Adds gid field, timestamps and markdown conversion to all tables.
    """

    @classmethod
    def __on_define__(cls, db: TypeDAL) -> None:
        """Configure field representers when the table is defined."""
        super().__on_define__(db)

        # otherwise py4web will represent it with a `document.write()` in US format which is ugly and also breaks htmx
        cls.created_at.represent = dutch_date
        cls.updated_at.represent = dutch_date
