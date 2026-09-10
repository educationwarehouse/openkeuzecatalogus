"""File-backed mock implementation of the error-signal service."""

import dataclasses as dc
import json
import os
from pathlib import Path

from .contracts import ErrorSignal, ErrorSignalService


class MockErrorSignalService(ErrorSignalService):
    """Append error signals as JSONL records for development and tests."""

    def __init__(self, output_path: Path) -> None:
        """Create the mock service writing to `output_path`."""
        self.output_path = output_path

    @classmethod
    def from_env(cls) -> MockErrorSignalService:
        """Build the mock service from its configured output path."""
        output_path = Path(os.environ.get("ERROR_SIGNAL_MOCK_PATH", "/shared_cache/error_signals/mock.jsonl"))
        return cls(output_path)

    def send_one(self, signal: ErrorSignal) -> bool:
        """Persist one signal payload for local inspection."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(dc.asdict(signal), ensure_ascii=True, sort_keys=True)
        print(f"[error-signal] {payload}")
        with self.output_path.open("a", encoding="utf-8") as file_pointer:
            file_pointer.write(payload)
            file_pointer.write("\n")
        return True
