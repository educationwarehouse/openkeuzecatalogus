"""Tests for decision-process schoolyear helpers."""

import datetime as dt

from shared_code.modules.decision_processes.helpers import (
    calculate_current_schoolyear,
    calculate_next_schoolyear,
    calculate_next_schoolyear_label,
    schoolyear_label,
)


def test_schoolyear_helpers_return_the_upcoming_schoolyear() -> None:
    """The upcoming schoolyear follows the academic year containing today."""
    today = dt.date.today()
    current_start_year = today.year if today.month >= 8 else today.year - 1
    next_start_year = current_start_year + 1

    assert calculate_current_schoolyear() == current_start_year
    assert calculate_next_schoolyear() == next_start_year
    assert calculate_next_schoolyear_label() == f"{next_start_year}-{next_start_year + 1}"


def test_schoolyear_label_formats_a_start_year() -> None:
    """A start year is rendered as one academic-year label."""
    assert schoolyear_label(2026) == "2026-2027"
