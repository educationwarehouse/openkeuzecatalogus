"""Performance diagnostics preserve application behavior and group nested work."""

from contextlib import redirect_stdout
from io import StringIO

import pytest

from shared_code.services.debug_performance import DebugPerformanceScope, DebugPerformanceService


def test_disabled_performance_measurements_emit_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    """Disabled scopes accept checkpoints and remain silent even when the operation fails."""
    service = DebugPerformanceService()
    with service("disabled") as scope:
        scope.checkpoint("ignored")
    error = ValueError("application failure")
    with pytest.raises(ValueError) as raised:
        with service("failed disabled"):
            raise error

    assert raised.value is error
    assert capsys.readouterr().out == ""


def test_nested_measurements_print_only_when_the_outer_scope_finishes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Child measurements appear once, beneath the parent interval that contains them."""
    service = DebugPerformanceService(enabled=True)
    with service("outer") as outer:
        with service("inner") as inner:
            inner.checkpoint("query")
        assert capsys.readouterr().out == ""
        outer.checkpoint("fetch")

    output = capsys.readouterr().out
    assert output.count("[debug_performance]") == 1
    assert output.count("outer:") == output.count("inner:") == 1
    assert "fetch" in output
    assert "query" in output
    assert "remaining" in output
    assert "    inner:" in output
    assert "[FAILED]" not in output


def test_failed_nested_measurements_preserve_the_error_and_next_scope(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unwinding marks failed scopes and does not attach later work to a stale parent."""
    service = DebugPerformanceService(enabled=True)
    error = RuntimeError("query failed")
    with pytest.raises(RuntimeError) as raised:
        with service("outer"):
            with service("inner"):
                raise error

    failed_output = capsys.readouterr().out
    assert raised.value is error
    assert failed_output.count("[FAILED]") == 2
    with service("recovered") as scope:
        scope.checkpoint("next query")
    output = capsys.readouterr().out
    assert output.startswith("[debug_performance] recovered:")
    assert "outer:" not in output
    assert "inner:" not in output
    assert "[FAILED]" not in output


def test_standalone_scope_can_be_reused_without_previous_checkpoints(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reusing a scope starts a new report instead of accumulating earlier measurements."""
    scope = DebugPerformanceScope("standalone", enabled=True)
    scope.checkpoint("before entry")
    with scope:
        scope.checkpoint("first query")
    capsys.readouterr()
    scope.checkpoint("after exit")
    with scope:
        scope.checkpoint("second query")

    output = capsys.readouterr().out
    assert "second query" in output
    assert "first query" not in output
    assert "before entry" not in output
    assert "after exit" not in output


class UnwritableOutput(StringIO):
    """Represent a stdout stream that can no longer accept diagnostic output."""

    def write(self, text: str) -> int:
        """Fail like a disconnected output stream."""
        raise OSError("output unavailable")


def test_output_failure_does_not_replace_an_application_exception() -> None:
    """A broken diagnostic stream must not hide the operation's original failure."""
    error = ValueError("original failure")
    with redirect_stdout(UnwritableOutput()), pytest.raises(ValueError) as raised:
        with DebugPerformanceScope("failed output", enabled=True):
            raise error

    assert raised.value is error
