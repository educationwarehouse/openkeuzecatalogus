"""UUID field factories for data-model tables."""

import typing as t
import uuid

from pydal import SQLCustomType
from typedal.fields import TypedField
from typedal.types import FieldSettings

from shared_code.data_model.validators.is_uuid import IS_UUID, IS_UUID_OR_NULL


def _uuid_sql_type(encoder: t.Callable[[t.Any], str | None]) -> SQLCustomType:
    sql_type = SQLCustomType(
        type="string",
        native="uuid",
        encoder=encoder,
        # decoder=_decode_uuid_value,
    )

    # py4web form rendering expects string-like field.type objects.
    sql_type.split = lambda on=None: str(sql_type).split(on)  # ty: ignore[unresolved-attribute]

    return sql_type


# noinspection PyPep8Naming
def InternalUUIDField(**kw: t.Unpack[FieldSettings]) -> TypedField[str]:
    """Database type is uuid, Python type is str."""
    settings: FieldSettings = {
        "type": _uuid_sql_type(lambda val: "" if val is None else str(val)),
        "default": uuid.uuid4,
        "writable": False,
        "requires": IS_UUID(),
    } | kw

    return TypedField(str, **settings)


# noinspection PyPep8Naming
def UUIDReferenceField(**kw: t.Unpack[FieldSettings]) -> TypedField[str]:
    """Reference an existing UUID without generating an unrelated identifier."""
    settings: FieldSettings = {"default": None} | kw

    return InternalUUIDField(**settings)


# noinspection PyPep8Naming
def OptionalUUIDField(**kw: t.Unpack[FieldSettings]) -> TypedField[str | None]:
    """Database type is nullable uuid, Python type is str | None."""
    settings: FieldSettings = {
        "type": _uuid_sql_type(lambda val: None if val is None else str(val)),
        "default": None,
        "requires": IS_UUID_OR_NULL(),
        "required": False,
    } | kw

    return TypedField(str | None, **settings)
