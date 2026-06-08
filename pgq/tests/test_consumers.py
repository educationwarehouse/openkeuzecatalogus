"""Tests for PGQ consumer wiring."""

from pgq.consumers import applog, scrapers


async def test_applog_main_returns_queue() -> None:
    """`applog.main` returns a configured queue."""
    pgq = await applog.main()
    assert pgq
    assert pgq.channel


def test_blocking_fn_returns_expected_value() -> None:
    """`blocking_fn` returns the expected value."""
    assert scrapers.blocking_fn() == "something"


async def test_scrapers_main_returns_queue() -> None:
    """`scrapers.main` returns a configured queue."""
    pgq = await scrapers.main()
    assert pgq
    assert pgq.channel
