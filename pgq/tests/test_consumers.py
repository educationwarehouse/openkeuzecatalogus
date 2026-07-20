"""Tests for PGQ consumer wiring."""

from pgq.consumers import applog, scrapers


async def test_applog_main_returns_queue() -> None:
    """`applog.main` returns a configured queue."""
    pgq = await applog.main()
    assert pgq
    assert pgq.channel


async def test_scrapers_main_returns_queue() -> None:
    """`scrapers.main` returns a configured queue."""
    pgq = await scrapers.main()
    assert pgq
    assert pgq.channel
