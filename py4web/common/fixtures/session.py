"""Session helpers used across the py4web app."""

import time
import typing as t
from datetime import timedelta

from ombott.request_pkg.errors import BodyParsingError

from py4web import HTTP, Session, request


class PoppableSession(Session):
    """A session that supports `pop` while persisting the change immediately."""

    def on_request(self, context: dict[str, t.Any]) -> None:
        """Reject malformed multipart bodies before loading the session."""
        if request.content_type.startswith("multipart/"):
            try:
                _ = request.forms
            except (BodyParsingError, UnicodeDecodeError) as error:
                raise HTTP(400, "Ongeldige formuliergegevens.") from error

        super().on_request(context)

    def _set_metadata(self, **metadata: t.Any) -> None:
        """Set fixture metadata without routing assignments into session data."""
        for name, value in metadata.items():
            object.__setattr__(self, name, value)

    def __init__(self, absolute_expiration: int = int(timedelta(days=30).total_seconds()), **kwargs: t.Any) -> None:
        """Limit authenticated sessions independently of sliding expiration."""
        super().__init__(**kwargs)
        self._set_metadata(absolute_expiration=absolute_expiration)

    def load(self) -> None:
        """Refresh active sessions and reject those past their login lifetime."""
        super().load()
        self.local.loaded_uuid = self.get("uuid")
        self.local.loaded_user = self.get("user")

        if self.get("uuid") and self.params.storage.get(f"session:revoked:{self.get('uuid')}"):
            self.clear()

        if self.get("user"):
            started = self.get("login_timestamp", self.get("timestamp", 0))
            if time.time() - started >= self.absolute_expiration:
                self.clear()
            else:
                self["login_timestamp"] = started

    def save(self) -> None:
        """Revoke rotated IDs and renew the inactivity deadline on each request."""
        previous_uuid = self.local.loaded_uuid

        if (
            previous_uuid
            and previous_uuid == self.get("uuid")
            and self.params.storage.get(f"session:revoked:{previous_uuid}")
        ):
            super().clear()

        if self.get("user") and (not self.local.loaded_user or self.get("uuid") != previous_uuid):
            self["login_timestamp"] = time.time()

        if previous_uuid and previous_uuid != self.get("uuid"):
            self._revoke(previous_uuid)

        super().save()
        self.local.loaded_uuid = self.get("uuid")
        self.local.loaded_user = self.get("user")

    def _revoke(self, session_uuid: str) -> None:
        """Keep an in-flight request from making a revoked ID usable again."""
        self.params.storage.set(f"session:revoked:{session_uuid}", "1", self.absolute_expiration)
        self.params.storage.delete(session_uuid)

    def clear(self) -> None:
        """Revoke the persisted session immediately, including on logout."""
        if session_uuid := self.get("uuid"):
            self._revoke(session_uuid)
        super().clear()

    def pop(self, key: t.Any, default: t.Any = None) -> t.Any:
        """Remove a key from the session and save the updated state."""
        data = self.get(key, default)
        del self[key]
        self.save()
        return data
