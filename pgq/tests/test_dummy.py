"""Smoke tests for PGQ connectivity."""

from pgskewer import ImprovedQueuer


async def test_dummy_pgq() -> None:
    """Queue creation from environment succeeds."""
    assert await ImprovedQueuer.from_env()
