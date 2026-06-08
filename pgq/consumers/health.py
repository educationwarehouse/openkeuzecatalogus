"""Shared file-based health markers for pgq worker containers."""

from pathlib import Path

HEARTBEAT_FILE = Path("/tmp/pgq-heartbeat")


def mark_heartbeat() -> None:
    """Update worker heartbeat timestamp."""
    HEARTBEAT_FILE.touch()
