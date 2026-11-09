"""Events shown in the discussion timeline on the public homepage."""

import datetime as dt
import typing as t

from pydal.validators import IS_IN_SET, IS_URL
from typedal.fields import TextField, TypedField

from shared_code.data_model.tables.base import TableWithGid

SourceType = t.Literal["blog", "pers", "rapport", "social media"]
SOURCE_TYPES = t.get_args(SourceType)


class TimelineEvent(TableWithGid):
    """One dated contribution with its source and modal description."""

    title = TypedField(str, required=True, length=500, label="Titel")
    source_type = TypedField(
        str,
        required=True,
        length=40,
        requires=IS_IN_SET(SOURCE_TYPES),
        label="Soort bron",
    )
    author = TypedField(str, required=True, length=500, label="Auteur of organisatie")
    event_date = TypedField(dt.date, required=True, label="Datum")
    url = TypedField(str, required=True, length=2048, requires=IS_URL(), label="Bron URL")
    description = TextField(label="Omschrijving")
