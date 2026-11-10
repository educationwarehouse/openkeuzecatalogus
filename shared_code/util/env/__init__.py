"""Shared environment parsing helpers."""

import os


def bool_from_env(name: str, default: bool = False) -> bool:
    """Parse a truthy/falsey environment variable into a boolean."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def int_from_env(name: str, default: int) -> int:
    """Parse an environment variable into an int, falling back on anything unusable.

    An empty or misspelled value is the default rather than a crash: these are
    settings, and one typo should not keep a service from starting.
    """
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default
