"""List representer helpers."""

import json
import typing as t


def json_load[T](value: str, default: T) -> T:
    """Parse JSON and return `default` when parsing fails."""
    try:
        return json.loads(value)
    except Exception:
        return default


def comma_separated(lst: list[str] | str, _: object) -> str:
    """Render a list (or JSON string list) as comma-separated text."""
    if isinstance(lst, str):
        lst = json_load(lst, t.cast(list[str], []))

    return ", ".join(lst) if lst else ""
