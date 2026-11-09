"""Types shared by the cache contract, its helpers and its backends."""

import dataclasses as dc
import typing as t
from datetime import timedelta

PUBLIC_SCOPE = "public"


@dc.dataclass(frozen=True, slots=True)
class GidDep:
    """A dependency on one logical entity, identified by its gid.

    Deliberately carries no table: a gid spans every effective-dated version of
    an entity, and the same gid turns up in other tables as a foreign column
    (`Tagged.subject_gid`, `SharedProductField.supplier_gid`). Invalidating the
    gid should reach all of them.
    """

    gid: str


@dc.dataclass(frozen=True, slots=True)
class RowDep:
    """A dependency on one exact row, for tables that mutate in place.

    Inert for effective-dated tables, where an update inserts a new row and
    leaves the row that was read untouched.
    """

    table: str
    id: int


@dc.dataclass(frozen=True, slots=True)
class TableDep:
    """A query's table, or one known logical entity within that table.

    A query without a gid includes rows that could enter its results later,
    even when its current result is empty.
    """

    table: str
    gid: str | None = None


type Dep = GidDep | RowDep | TableDep
type DepSet = set[Dep]


@t.runtime_checkable
class ScopeIdentity(t.Protocol):
    """The actor-shaped half of a scope, as `AuthActor` provides it.

    Read-only: a scope is only ever asked what it is, never told. Declaring the
    members as plain attributes would demand they be writable, which rules out
    the frozen dataclasses that actors usually are.
    """

    @property
    def kind(self) -> str:
        """Return what sort of actor this is, `anonymous` among them."""

    @property
    def id(self) -> str | None:
        """Return the actor's identifier, absent for an anonymous one."""


type Scope = ScopeIdentity | str | None
"""Who a cached entry belongs to.

An actor for per-user results, a plain string for a coarser discriminator such
as a role or tenant, or `None` for data everybody may share.
"""

type TTL = int | float | timedelta | None
