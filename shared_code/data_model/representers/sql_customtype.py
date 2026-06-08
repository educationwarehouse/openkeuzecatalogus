"""Compatibility helpers for SQL custom types."""

from typedal import TypedField


def fix_sqlcustomtype(field: TypedField) -> None:
    """Make non-string `field.type` compatible with py4web form rendering.

    Dirty hack for this error:
    >>  File "/opt/venv/lib/python3.13/site-packages/py4web/utils/form.py", line 395, in __call__
    >>  field_class = "type-" + field.type.split()[0].replace(":", "-")
    >>                          ^^^^^^^^^^^^^^^^
    >>  AttributeError: 'SQLCustomType' object has no attribute 'split'
    """
    if not isinstance(field.type, str):
        field.type.split = lambda on=None: str(field.type).split(on)  # type: ignore
