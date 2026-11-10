"""Tests for date and list representer helpers."""

import datetime as dt
from decimal import Decimal

import pytest
import pytz

from shared_code.data_model.representers.dates import dutch_date
from shared_code.data_model.representers.lists import comma_separated
from shared_code.data_model.representers.numbers import dutch_currency


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "€\u00a00,00"),
        (Decimal("1234.56"), "€\u00a01.234,56"),
        ("-1234.56", "€\u00a0-1.234,56"),
        ("Op aanvraag", "Op aanvraag"),
        ("NaN", "NaN"),
    ],
)
def test_dutch_currency_uses_dutch_locale(value: int | Decimal | str, expected: str) -> None:
    """Currency formatting handles grouping, negative values and non-price text."""
    assert dutch_currency(value) == expected


def test_dutch_date_returns_empty_string_for_none() -> None:
    """Return an empty string when no date value is provided."""
    assert dutch_date(None) == ""


def test_dutch_date_returns_original_string_for_non_date_input() -> None:
    """Return string inputs unchanged."""
    assert dutch_date("already formatted") == "already formatted"


def test_dutch_date_formats_date_without_time() -> None:
    """Format plain dates using the default Dutch format."""
    date_value = dt.date(2026, 1, 2)
    assert dutch_date(date_value) == "02-01-2026"


def test_dutch_date_converts_naive_datetime_from_utc_to_target_timezone() -> None:
    """Convert naive datetimes from UTC into the target timezone."""
    value = dt.datetime(2026, 1, 2, 12, 0, 0)
    timezone = pytz.timezone("Europe/Amsterdam")
    assert dutch_date(value, timezone=timezone) == "02-01-2026 13:00:00"


def test_dutch_date_uses_custom_format() -> None:
    """Apply a custom output format when provided."""
    value = dt.datetime(2026, 6, 1, 12, 34, 56)
    timezone = pytz.timezone("Europe/Amsterdam")
    assert dutch_date(value, timezone=timezone, str_format="%Y/%m/%d %H:%M") == "2026/06/01 14:34"


def test_comma_separated_with_list() -> None:
    """Join list values with commas."""
    assert comma_separated(["a", "b", "c"], None) == "a, b, c"


def test_comma_separated_with_json_string_list() -> None:
    """Parse and join JSON-array strings."""
    assert comma_separated('["x", "y"]', None) == "x, y"


def test_comma_separated_with_invalid_json_string_returns_empty() -> None:
    """Return empty output for invalid JSON strings."""
    assert comma_separated("not-json", None) == ""


def test_comma_separated_with_empty_values_returns_empty() -> None:
    """Return empty output for empty inputs."""
    assert comma_separated([], None) == ""
    assert comma_separated("", None) == ""
