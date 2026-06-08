"""Diskcache-backed applog implementation."""

from __future__ import annotations

import json
import os

from diskcache import Deque

from ..time.clock import normalize_timestamp, utcnow
from .contracts import ApplogEvent, Applogger, ApplogSignal


class DequeApplogger(Applogger):
    """Persist applog events to a local deque for async DB processing."""

    def __init__(self, directory: str = "/shared_applog", signal_source: str = "py4web") -> None:
        """Create a deque-backed applogger for async signal processing."""
        self.signal_source = signal_source
        self.deque = Deque(directory=directory)

    @classmethod
    def from_env(cls) -> Applogger:
        """Build a deque-backed applogger from environment configuration."""
        directory = os.environ.get("APPLOG_DEQUE_DIR", "/shared_applog")
        return cls(directory=directory)

    def fire(self, event: ApplogEvent) -> bool:
        """Serialize and enqueue one applog signal payload."""
        timestamp = event.get("timestamp") or utcnow()
        related = event.get("related")

        signal: ApplogSignal = {
            "name": event.get("kind", "") or "event",
            "signal_source": self.signal_source,
            "evidence": event,
            "session_gid": None,
            "user_gid": event.get("user_gid"),
            "ts": normalize_timestamp(timestamp),
            "related": str(related) if related else None,
        }
        payload = json.dumps(
            signal,
            ensure_ascii=True,
            sort_keys=True,
            default=str,
        )
        with self.deque.transact():
            self.deque.append(payload)
        return True
