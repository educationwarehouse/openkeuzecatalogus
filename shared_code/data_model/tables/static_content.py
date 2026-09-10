"""Persisted content for editable public-page sections."""

from typedal.fields import TextField, TypedField

from shared_code.data_model.tables.base import TableWithGid


class StaticContent(TableWithGid):
    """An HTML content section identified by its template scope and section id."""

    scope = TypedField(str, length=120)
    section = TypedField(str, length=120)
    content = TextField()
