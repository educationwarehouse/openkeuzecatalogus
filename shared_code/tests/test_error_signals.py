"""Tests for asynchronous error-ticket signaling."""

import json
from pathlib import Path

import pytest

from shared_code.modules.auth import AuthAdapter
from shared_code.services.error_signals import ErrorSignalService, MockErrorSignalService
from shared_code.services.error_tickets import (
    AuthInfo,
    ErrorTicket,
    ErrorTicketService,
    ExceptionInfo,
    MetaInfo,
)


def _ticket(ticket_id: str) -> ErrorTicket:
    """Build one stored-ticket payload without request or user data."""
    return ErrorTicket(
        meta=MetaInfo(
            ticket_id=ticket_id,
            timestamp="2026-07-23T10:00:00+00:00",
            hosting_domain="catalog.example.test",
            application="catalog",
            project="open-catalog",
        ),
        request=None,
        exception=ExceptionInfo(type="RuntimeError", message="Import failed", traceback="hidden traceback"),
        auth=AuthInfo(),
        context={},
    )


def _configure_signal_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Configure an isolated mock signal backend and queue."""
    mock_path = tmp_path / "signals.jsonl"
    monkeypatch.setenv("ERROR_SIGNAL_BACKEND", "mock")
    monkeypatch.setenv("ERROR_SIGNAL_QUEUE_PATH", str(tmp_path / "pending"))
    monkeypatch.setenv("ERROR_SIGNAL_MOCK_PATH", str(mock_path))
    monkeypatch.setenv("HOSTINGDOMAIN", "catalog.example.test")
    return mock_path


def test_mock_backend_is_selected_from_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The configured mock backend should be selected without network setup."""
    _configure_signal_paths(monkeypatch, tmp_path)

    service = ErrorSignalService.with_injected()

    assert isinstance(service, MockErrorSignalService)


def test_ticket_signals_are_delivered_in_configured_batches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Queued tickets should produce safe mock payloads and direct admin links."""
    mock_path = _configure_signal_paths(monkeypatch, tmp_path)
    error_tickets = ErrorTicketService.with_injected(auth_adapter=AuthAdapter.for_service("pytest.error_signals"))
    error_tickets.enqueue_ticket_signal(_ticket("OPEN-CATALOG-1"))
    error_tickets.enqueue_ticket_signal(_ticket("OPEN-CATALOG-2"))

    assert error_tickets.process_ticket_signal_queue(batch_size=1) == 1
    assert error_tickets.process_ticket_signal_queue(batch_size=1) == 1
    assert error_tickets.process_ticket_signal_queue() == 0

    payloads = [json.loads(line) for line in mock_path.read_text(encoding="utf-8").splitlines()]
    assert [payload["ticket_id"] for payload in payloads] == ["OPEN-CATALOG-1", "OPEN-CATALOG-2"]
    assert payloads[0]["click_url"] == "https://catalog.example.test/admin/errors/OPEN-CATALOG-1"
    assert "traceback" not in payloads[0]
    assert "auth" not in payloads[0]
    assert "request" not in payloads[0]
    assert "[error-signal]" in capsys.readouterr().out


def test_queued_signal_uses_the_injected_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Queue processing should keep using the backend injected into the ticket service."""
    _configure_signal_paths(monkeypatch, tmp_path)
    error_tickets = ErrorTicketService.with_injected(auth_adapter=AuthAdapter.for_service("pytest.error_signals"))
    error_tickets.enqueue_ticket_signal(_ticket("OPEN-CATALOG-3"))
    monkeypatch.setenv("ERROR_SIGNAL_BACKEND", "unsupported")

    assert error_tickets.process_ticket_signal_queue() == 1
    assert error_tickets.process_ticket_signal_queue() == 0
    assert "[error-signal]" in capsys.readouterr().out
