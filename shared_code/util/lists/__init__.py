"""List helper utilities."""

import typing as t


def uniq[H: t.Hashable](items: t.Iterable[H]) -> list[H]:
    """Remove duplicates while preserving order.

    Requires hashable items (str, int, not dict)
    """
    return list(dict.fromkeys(items))
