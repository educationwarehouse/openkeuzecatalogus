"""Helpers for guided learning-material decision processes."""

import datetime as dt


def calculate_current_schoolyear() -> int:
    """Return the start year of the academic year containing today."""
    today = dt.date.today()
    # split at august:
    return today.year if today.month >= 8 else today.year - 1


def calculate_next_schoolyear() -> int:
    """Return the start year of the academic year after the current one."""
    return calculate_current_schoolyear() + 1


def schoolyear_label(start_year: int) -> str:
    """Format one start year as an academic-year label."""
    return f"{start_year}-{start_year + 1}"


def calculate_next_schoolyear_label() -> str:
    """Return the upcoming schoolyear label, e.g. `2026-2027`."""
    return schoolyear_label(calculate_next_schoolyear())


__all__ = [
    "calculate_current_schoolyear",
    "calculate_next_schoolyear",
    "calculate_next_schoolyear_label",
    "schoolyear_label",
]
