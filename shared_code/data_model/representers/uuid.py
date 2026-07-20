"""UUID representers for table fields."""

import typing as t
from uuid import UUID

from typedal import TypedTable

if t.TYPE_CHECKING:
    from yatl import TAGGER as HTMLElement


def short_uuid(gid: str | UUID, _row: TypedTable | None = None) -> HTMLElement:
    """Render a UUID as a clickable clipboard icon."""
    from yatl import INPUT, I

    gid = str(gid)
    return I(
        INPUT(
            _type="hidden",
            _name="gid",
            _value=gid,
        ),
        _class="far fa-clipboard center-in-cell",
        _title=gid,
        __=f"""
            on click
                call navigator.clipboard.writeText('{gid}')
                then remove .text-success from .fa-clipboard
                then add .text-success to me
            """,
    )
