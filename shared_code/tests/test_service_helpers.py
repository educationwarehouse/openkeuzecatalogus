"""Unit tests for shared service helper functions."""

import datetime as dt

import pytest

from shared_code.infra.database import catch_errors
from shared_code.services.applog.contracts import ApplogEvent, Applogger
from shared_code.util.env import bool_from_env
from shared_code.util.time import normalize_timestamp


def test_normalize_timestamp_from_datetime_returns_isoformat() -> None:
    """Datetime inputs should normalize via isoformat()."""
    value = dt.datetime(2026, 1, 2, 3, 4, 5)
    assert normalize_timestamp(value) == value.isoformat()


def test_normalize_timestamp_from_unix_timestamp_returns_isoformat() -> None:
    """Numeric Unix timestamps should be converted to datetime then isoformat()."""
    unix_ts = 0
    expected = dt.datetime.fromtimestamp(unix_ts).isoformat()
    assert normalize_timestamp(unix_ts) == expected


def test_bool_from_env_returns_default_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing env values should use the provided default."""
    monkeypatch.delenv("UNIT_TEST_BOOL_MISSING", raising=False)
    assert bool_from_env("UNIT_TEST_BOOL_MISSING", default=True) is True
    assert bool_from_env("UNIT_TEST_BOOL_MISSING", default=False) is False


def test_bool_from_env_parses_truthy_and_falsey(monkeypatch: pytest.MonkeyPatch) -> None:
    """Truthy tokens should map to True; non-truthy values should map to False."""
    monkeypatch.setenv("UNIT_TEST_BOOL_PARSE", "  YeS  ")
    assert bool_from_env("UNIT_TEST_BOOL_PARSE") is True

    monkeypatch.setenv("UNIT_TEST_BOOL_PARSE", "0")
    assert bool_from_env("UNIT_TEST_BOOL_PARSE") is False


def test_catch_errors_logs_and_reraises_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """When an exception occurs, catch_errors should fire applog error event and reraise."""

    class _FakeApplogger(Applogger):
        def __init__(self) -> None:
            self.fired_events: list[ApplogEvent] = []

        def fire(self, event: ApplogEvent) -> bool:
            self.fired_events.append(event)
            return True

    fake_logger = _FakeApplogger()
    monkeypatch.setattr( # noqa: EW001
        "shared_code.infra.database.Applogger.from_env",
        lambda: fake_logger,
    )
    fixed_now = dt.datetime(2026, 6, 1, 10, 11, 12, tzinfo=dt.UTC)
    monkeypatch.setattr("shared_code.services.applog.contracts.utcnow", lambda: fixed_now)  # noqa: EW001

    with pytest.raises(ValueError, match="boom"), catch_errors("unit.test.app"):
        raise ValueError("boom")

    assert len(fake_logger.fired_events) == 1
    event = fake_logger.fired_events[0]
    assert event["timestamp"] == fixed_now
    assert event["kind"] == "error"
    assert event["action"] is None
    assert event["details"] == {"application": "unit.test.app"}
