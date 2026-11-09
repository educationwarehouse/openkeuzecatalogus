"""Shared UI constants.

Kept dependency-free on purpose: both the fixture chain and the grid helpers import
from here, and neither may pull in `common.models` (which initialises the database).
"""

BUTTON_CLASS = "btn btn-sm btn-secondary"

__all__ = ["BUTTON_CLASS"]
