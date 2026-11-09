"""Tests for the custom multi-value pyDAL validator."""

import pytest
from pydal.validators import ValidationError

from shared_code.data_model.validators.is_in_set_fixed import IS_IN_SET_FIXED


def test_is_in_set_fixed_validates_multiple_values_and_tolerates_empty_options() -> None:
    """Multiple values honour bounds and known options, except for an empty option set."""
    validator = IS_IN_SET_FIXED([2, 1], multiple=(1, 3))

    assert validator.validate([2, 1]) == [2, 1]

    with pytest.raises(ValidationError):
        validator.validate([])

    with pytest.raises(ValidationError):
        validator.validate([1, 2, 3])

    with pytest.raises(ValidationError):
        validator.validate([3])

    assert IS_IN_SET_FIXED([], multiple=True).validate(["new-value"]) == ["new-value"]
