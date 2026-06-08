"""Application logging service contracts."""

from __future__ import annotations

import abc
import datetime as dt
import json
import typing as t
from uuid import UUID

from typedal import TypeDAL

from shared_code.services.env import bool_from_env


class ApplogEvent(t.TypedDict, total=False):
    """Normalized applog event payload that can be persisted as evidence."""

    timestamp: dt.datetime | str | int
    kind: t.Literal["auth_action", "error", "event"]
    action: str | None
    details: str | dict
    related: t.NotRequired[str | UUID]
    # ...


class ApplogSignal(t.TypedDict):
    """Signal envelope used for queued applog processing."""

    name: str
    signal_source: str
    evidence: ApplogEvent
    session_gid: str | None
    user_gid: str | None
    ts: str
    related: str | None


class AuthEvent(ApplogEvent):
    """Specialized applog event shape for authentication actions."""

    user_gid: str | None
    email: str | None
    success: bool | None
    ip: str | None
    user_agent: str | None


class Applogger(abc.ABC):
    """Abstract app logger contract with shared event helpers."""

    db: TypeDAL

    @abc.abstractmethod
    def fire(self, event: ApplogEvent) -> bool:
        """Persist a normalized applog event payload."""
        ...

    def write_auth_event(self, event: AuthEvent) -> bool:
        """Backward-compatible auth-specific writer alias."""
        return self.fire(event)

    def log_auth_action(
        self,
        action: str,
        user_gid: UUID | str | None = None,
        email: str | None = None,
        success: bool | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
        details: t.Mapping[str, t.Any] | None = None,
    ) -> bool:
        """Build and persist (or enqueue) an auth action log event."""
        event = self._build_auth_event(
            action=action,
            user_gid=user_gid,
            email=email,
            success=success,
            ip=ip,
            user_agent=user_agent,
            details=details,
        )
        # Queueing belongs in a separate implementation; base contract is sync only.
        return self.fire(event)

    @classmethod
    def from_env(cls) -> Applogger:
        """Instantiate the configured applogger from environment settings."""
        if bool_from_env("APPLOG_FAKE", False):
            from .file import FileApplogger

            return FileApplogger.from_env()
        else:
            from .deque import DequeApplogger

            return DequeApplogger.from_env()

    @staticmethod
    def _build_auth_event(
        action: str,
        user_gid: UUID | str | None,
        email: str | None,
        success: bool | None,
        ip: str | None,
        user_agent: str | None,
        details: t.Mapping[str, t.Any] | None,
    ) -> AuthEvent:
        normalized_details = dict(details or {})
        return {
            "timestamp": dt.datetime.now(tz=dt.UTC).isoformat(),
            "kind": "auth_action",
            "action": action,
            "user_gid": str(user_gid) if user_gid else None,
            "email": email,
            "success": success,
            "ip": ip,
            "user_agent": user_agent,
            "details": json.loads(json.dumps(normalized_details, default=str)),
        }
