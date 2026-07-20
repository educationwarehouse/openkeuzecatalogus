"""Shared environment parsing helpers."""

import os


def bool_from_env(name: str, default: bool = False) -> bool:
    """Parse a truthy/falsey environment variable into a boolean."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
