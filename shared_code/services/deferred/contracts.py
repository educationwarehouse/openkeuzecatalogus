"""Contracts for durable, out-of-request work."""

import abc
import dataclasses as dc
import typing as t
import uuid

from endow import Service

from shared_code.data_model import AnyMapping

type DeferredStatus = t.Literal["pending", "success", "failure", "missing"]


@dc.dataclass(frozen=True, slots=True)
class DeferredJob:
    """Opaque reference to one deferred-work submission."""

    key: uuid.UUID
    entrypoint: str


@dc.dataclass(frozen=True, slots=True)
class DeferredResult:
    """The current externally useful state of deferred work."""

    status: DeferredStatus
    value: object | None = None


@dc.dataclass(frozen=True, slots=True)
class DeferredPoll[ContextT: AnyMapping]:
    """A deferred job and the signed context that authorises polling it."""

    job: DeferredJob
    context: ContextT


class DeferredWork(Service, abc.ABC):
    """Queue transport contract, independent from individual job behaviour."""

    @abc.abstractmethod
    def enqueue(self, entrypoint: str, payload: AnyMapping) -> DeferredJob:
        """Persist one payload for processing by a registered entrypoint."""
        ...

    @abc.abstractmethod
    def result(self, job: DeferredJob) -> DeferredResult:
        """Return the current terminal or pending state of deferred work."""
        ...

    @abc.abstractmethod
    def create_poll_token[ContextT: AnyMapping](self, job: DeferredJob, context: ContextT) -> str:
        """Create a short-lived signed capability for polling one job."""
        ...

    @abc.abstractmethod
    def resolve_poll_token[ContextT: AnyMapping](self, token: str) -> DeferredPoll[ContextT]:
        """Validate a polling capability and recover its job and context."""
        ...

    @classmethod
    def from_env(cls) -> DeferredWork:
        """Build the PGQ implementation used by this application."""
        from .pgq import PgqDeferredWork

        return PgqDeferredWork.from_env()
