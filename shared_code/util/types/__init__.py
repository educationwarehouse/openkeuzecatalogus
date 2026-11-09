"""Reusable type aliases and protocols.

Both exist because `str` is itself a `Sequence[str]`: a parameter typed that way
accepts `"a,b"` and then iterates it per character. Neither alias admits a bare
string.
"""

import typing as t


@t.runtime_checkable
class CachableProtocol(t.Protocol):
    """Convert database-bound values to plain copies for dill and restore them."""

    def to_dillable(self) -> t.Self:
        """Return a copy that dill can serialize without live resource handles."""
        ...

    @classmethod
    def from_dillable(cls, value: t.Self) -> t.Self:
        """Restore a cached copy using currently bound resources."""
        ...


# several values, order irrelevant: what `belongs()` and membership checks take
type MultiValue[T] = list[T] | tuple[T, ...] | set[T] | frozenset[T]

# several values whose order the caller relies on, so sets are out as well
type Ordered[T] = list[T] | tuple[T, ...]
