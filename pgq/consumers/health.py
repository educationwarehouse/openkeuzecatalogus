"""Shared file-based health markers for pgq worker containers."""

from pathlib import Path

HEARTBEAT_FILE = Path("/tmp/pgq-heartbeat")  # noqa: S108 - this is a fixed path on purpose


def mark_heartbeat() -> None:
    """Update worker heartbeat timestamp."""
    HEARTBEAT_FILE.touch()
