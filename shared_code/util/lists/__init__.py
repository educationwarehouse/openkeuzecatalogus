"""List helper utilities."""

import typing as t

from diskcache import Deque


def uniq[H: t.Hashable](items: t.Iterable[H]) -> list[H]:
    """Remove duplicates while preserving order.

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
            buffer.append(deque.popleft())
        except IndexError:
            break
    return buffer
