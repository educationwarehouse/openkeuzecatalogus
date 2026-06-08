"""Tests for UUID validation helpers."""

import uuid

from shared_code.data_model.validators.is_uuid import IS_UUID, is_uuid


def test_is_uuid_accepts_uuid_instance() -> None:
    """Accept UUID instances."""
    value = uuid.uuid4()
    assert is_uuid(value) is True


def test_is_uuid_accepts_valid_uuid_string_with_whitespace() -> None:
    """Accept UUID strings with surrounding whitespace."""
    value = f"  {uuid.uuid4()}  "
    assert is_uuid(value) is True


def test_is_uuid_rejects_invalid_string() -> None:
    """Reject invalid UUID strings."""
    assert is_uuid("not-a-uuid") is False


def test_is_uuid_rejects_non_string_non_uuid() -> None:
    """Reject values that are neither strings nor UUID objects."""
    assert is_uuid(123) is False


def test_is_uuid_callable_returns_uuid_and_no_error_on_success() -> None:
    """Return parsed UUID and no error for valid input."""
    validator = IS_UUID()
    raw_value = f" {uuid.uuid4()} "
    parsed, error = validator(raw_value)

    assert isinstance(parsed, uuid.UUID)
    assert error is None


def test_is_uuid_callable_returns_value_and_error_on_failure() -> None:
    """Return original value and message for invalid input."""
    validator = IS_UUID(error_message="Invalid UUID: ")
    value = "bad-value"
    parsed, error = validator(value)

    assert parsed is None
    assert error == "Invalid UUID: 'bad-value'"
