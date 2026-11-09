"""Tests for typed request-value conversion."""

import typing as t
from enum import Enum

import pytest
from common.fixtures.settings import convert_to_bool, convert_typed_value

from shared_code.data_model import Predicate


def test_convert_list_annotation_single_value_uses_normalize_value() -> None:
    """A scalar becomes a one-item string list."""
    converted = convert_typed_value("gid-1", list[str])
    assert converted == ["gid-1"]


def test_convert_list_annotation_list_value_uses_normalize_value() -> None:
    """A submitted string list stays a string list."""
    converted = convert_typed_value(["gid-1"], list[str])
    assert converted == ["gid-1"]


def test_convert_list_annotation_csv_value_uses_normalize_value() -> None:
    """Comma-separated values become a string list."""
    converted = convert_typed_value("gid-1,gid-2", list[str])
    assert converted == ["gid-1", "gid-2"]


def test_convert_to_bool_uses_project_behavior() -> None:
    """Boolean conversion accepts the project's HTML form values."""
    assert convert_to_bool("off") is False
    assert convert_to_bool("yes") is True


class PlainEnum(Enum):
    """Simple non-string enum used to verify enum conversion."""

    A = "a"
    B = "b"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", True),
        ("on", True),
        ("yes", True),
        ("true", True),
        ("0", False),
        ("off", False),
        ("no", False),
        (0, False),
        (1, True),
    ],
)
def test_convert_bool_values(raw: str | int, expected: bool) -> None:
    """Supported scalar values normalize to booleans."""
    assert convert_typed_value(raw, bool) is expected


def test_convert_int_and_str_values() -> None:
    """Basic scalar constructors normalize request values."""
    assert convert_typed_value("42", int) == 42
    assert convert_typed_value(123, str) == "123"


def test_convert_any_and_object_leave_value_unchanged() -> None:
    """Unconstrained annotations preserve their input object."""
    payload = {"key": "value"}
    assert convert_typed_value(payload, t.Any) is payload
    assert convert_typed_value(payload, object) is payload
    assert convert_typed_value(payload, None) is payload


def test_convert_literal_accepts_allowed_value() -> None:
    """Allowed literal values are accepted."""
    annotation = t.Literal["tagged", "parent"]
    assert convert_typed_value("tagged", annotation) == "tagged"


def test_convert_literal_rejects_disallowed_value() -> None:
    """Disallowed literal values fail conversion."""
    annotation = t.Literal["tagged", "parent"]
    with pytest.raises(ValueError):
        convert_typed_value("meta", annotation)


def test_convert_enum_value_plain_enum() -> None:
    """Enum annotations construct their matching member."""
    assert convert_typed_value("a", PlainEnum) is PlainEnum.A


def test_convert_union_to_str_enum_from_string() -> None:
    """Union conversion selects a matching enum member."""
    annotation = Predicate | t.Literal["tagged"]
    converted = convert_typed_value("bundles", annotation)
    assert converted is Predicate.BUNDLES


def test_convert_union_to_literal() -> None:
    """Union conversion selects a matching literal value."""
    annotation = Predicate | t.Literal["tagged"]
    converted = convert_typed_value("tagged", annotation)
    assert converted == "tagged"


def test_convert_union_with_multiple_non_literal_options() -> None:
    """Union conversion tries each scalar option in annotation order."""
    annotation = int | bool
    assert convert_typed_value("10", annotation) == 10


def test_convert_union_rejects_invalid_values() -> None:
    """Union conversion reports values matching no option."""
    annotation = Predicate | t.Literal["tagged"]
    with pytest.raises(TypeError):
        convert_typed_value("not-a-relation", annotation)


class WrappedString:
    """Simple custom type used to verify constructor conversion."""

    def __init__(self, value: str) -> None:
        """Store the converted value."""
        self.value = value


def test_convert_custom_type_annotation_uses_constructor() -> None:
    """Custom annotations receive the submitted value through their constructor."""
    converted = convert_typed_value("hello", WrappedString)
    assert isinstance(converted, WrappedString)
    assert converted.value == "hello"
