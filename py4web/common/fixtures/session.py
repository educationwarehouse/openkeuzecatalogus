"""Session helpers used across the py4web app."""

import typing as t

from py4web import Session


class PoppableSession(Session):
    """A session that supports ``pop`` while persisting the change immediately."""

    def pop(self, key: t.Any, default: t.Any = None) -> t.Any:
        """Remove a key from the session and save the updated state."""
        data = self.get(key, default)
        del self[key]
        self.save()
        return data
