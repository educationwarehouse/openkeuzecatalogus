"""File-backed applog implementation."""

import json
import os
from pathlib import Path

from .contracts import ApplogEvent, Applogger


class FileApplogger(Applogger):
    """Persist applog events as JSONL rows in a local file."""

    def __init__(self, path: str) -> None:
        """Create a file-backed applogger writing JSONL rows to `path`."""
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> Applogger:
        """Build a file-backed applogger from environment configuration."""
        path = os.environ.get("APPLOG_PATH", "/shared_applog/events.jsonl")
        return cls(path=path)

    def fire(self, event: ApplogEvent) -> bool:
        """Append a normalized event to the configured JSONL file."""
        try:
            payload = json.dumps(event, sort_keys=True, default=str)
            print(f"[applog] {payload}")
        except Exception as e:
            print("[applog] failed to JSON dump event:", event, e)
            return False

        with self.path.open("a", encoding="utf-8") as fp:
            fp.write(payload)
            fp.write("\n")

        return True
