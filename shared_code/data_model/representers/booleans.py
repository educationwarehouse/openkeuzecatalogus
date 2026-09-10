"""Boolean field representer helpers."""

import typing as t


def dutch_bool(value: bool, *_: t.Any) -> str:
    """Render a boolean as the Dutch yes/no labels used in table representations."""
    return "Ja" if value else "Nee"
