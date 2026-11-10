"""List helper utilities."""

import typing as t

from diskcache import Deque


def new_list[T]() -> list[T]:
    """Return a fresh list for use as a callable field default."""
    return []


def listify[T](value: T | t.Iterable[T]) -> list[T]:
    """Normalize a scalar or iterable value to a list.

    Form fields arrive as a scalar when one value was submitted and as a list when several
    were, so anything reading them back needs this.
    """
    if not value:
        return []

    if isinstance(value, list):
        return value
    elif isinstance(value, (set, tuple)):
        return list(t.cast(t.Iterable[T], value))
    else:
        return [t.cast(T, value)]


def uniq[H: t.Hashable](items: t.Iterable[H]) -> list[H]:
    """Remove duplicates while preserving order, unlike a set.

    Requires hashable items (str, int, not dict)
    """
    return list(dict.fromkeys(items))


def batch_deque[T](deque: Deque, batch_size: int) -> list[T]:
    """Pop up to `batch_size` items from a disk-backed deque."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    buffer: list[T] = []
    for _ in range(batch_size):
        try:
            buffer.append(t.cast(T, deque.popleft()))
        except IndexError:
            break
    return buffer
