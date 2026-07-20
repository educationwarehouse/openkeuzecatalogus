"""Application logging service contracts."""

import abc
import datetime as dt
import json
import typing as t
from uuid import UUID

from endow import Service

from shared_code.util.env import bool_from_env
from shared_code.util.time import utcnow

if t.TYPE_CHECKING:
    from shared_code.infra.database import DatabaseContext


class ApplogEvent(t.TypedDict, total=False):
    """Normalized applog event payload that can be persisted as evidence."""

    timestamp: dt.datetime | str | int
    kind: t.Literal["auth_action", "error", "event"]
    action: str | None
    details: str | dict
    user_gid: str | None
    related: str | UUID | None
    # ...


class AuthEvent(ApplogEvent):
    """Specialized applog event shape for authentication actions."""

    email: str | None
    success: bool | None
    ip: str | None
    user_agent: str | None


class ApplogSignal(t.TypedDict):
    """Signal envelope used for queued applog processing."""

    # not used manually

    name: str
    signal_source: str
    evidence: ApplogEvent
    session_gid: str | None
    user_gid: str | None
    ts: str
    related: str | None


class Applogger(Service, abc.ABC):
    """Abstract app logger contract with shared event helpers."""

    db: DatabaseContext

    @abc.abstractmethod
    def fire(self, event: ApplogEvent) -> bool:
        """Persist a normalized applog event payload."""
        ...

    def try_fire(self, event: ApplogEvent) -> bool:
        """Attempt to persist an event and swallow unexpected failures."""
        try:
            if "timestamp" not in event:
                event["timestamp"] = utcnow()
            return self.fire(event)
        except Exception as e:
            print(f"[applog] failed with {e}")
            return False

    def write_auth_event(self, event: AuthEvent) -> bool:
        """Backward-compatible auth-specific writer alias."""
        return self.try_fire(event)

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
        return self.try_fire(event)

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
            "timestamp": utcnow().isoformat(),
            "kind": "auth_action",
            "action": action,
            "user_gid": str(user_gid) if user_gid else None,
            "email": email,
            "success": success,
            "ip": ip,
            "user_agent": user_agent,
            "details": json.loads(json.dumps(normalized_details, default=str)),
        }
