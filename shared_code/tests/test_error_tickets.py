"""Tests for structured error ticket persistence."""

import typing as t
from pathlib import Path

from pytest import MonkeyPatch

from shared_code.services.error_tickets import (
    AuthInfo,
    ErrorTicketService,
    ExceptionInfo,
    RequestInfo,
    SnapshotDict,
)


def _raise_and_store_ticket(
    error_tickets: ErrorTicketService,
    context: dict[str, t.Any],
    snapshot: SnapshotDict | None = None,
) -> str:
    """Store a ticket while an exception is active so traceback capture is real."""
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        return error_tickets.try_store(context, snapshot=snapshot)


def _ticket_env(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """Configure ticket storage and metadata through environment variables."""
    monkeypatch.setenv("ERROR_CACHE_PATH", str(tmp_path / "errors"))
    monkeypatch.setenv("APPLICATION_NAME", "unit-app")
    monkeypatch.setenv("HOSTINGDOMAIN", "example.test")
    monkeypatch.setenv("PROJECT", "ticketproj")


def test_store_and_load_ticket_round_trips_real_data(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """A stored ticket should be readable back into the same dataclasses."""
    _ticket_env(monkeypatch, tmp_path)
    error_tickets = ErrorTicketService.with_injected()

    context = {"application": "ticket-tests", "details": {"nested": ["a", "b"]}}
    snapshot = {
        "auth": AuthInfo(user_email="alice@example.com", user_groups=["admin", "editor"]),
        "request": RequestInfo(
            path="/tickets/42",
            method="POST",
            query_string="page=1&access_token=secret-token",
            headers={
                "Authorization": "Bearer secret-token",
                "Cookie": "session=abc123",
                "User-Agent": "pytest",
                "X-Test": "1",
            },
            form_vars={
                "email": "alice@example.com",
                "password": "plaintext-password",
                "callback_data": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.signature",
            },
            cookies={"session": "abc123"},
            remote_addr="127.0.0.1",
            user_agent="pytest",
        ),
    }

    ticket_id = _raise_and_store_ticket(error_tickets, context, snapshot=snapshot)
    ticket_path = tmp_path / "errors" / f"{ticket_id}.toml"

    assert ticket_id.startswith("TICKETPROJ-")
    assert ticket_path.is_file()

    ticket = error_tickets.load(ticket_id)
    assert ticket is not None
    assert ticket.meta.ticket_id == ticket_id
    assert ticket.meta.application == "ticket-tests"
    assert ticket.meta.hosting_domain == "example.test"
    assert ticket.meta.project == "ticketproj"
    assert ticket.exception == ExceptionInfo(
        type="RuntimeError",
        message="boom",
        traceback=ticket.exception.traceback,
    )
    assert "RuntimeError: boom" in ticket.exception.traceback
    assert ticket.auth == snapshot["auth"]
    assert ticket.request is not None
    assert ticket.request.query_string == "page=1&access_token=%3Credacted%3E"
    assert ticket.request.headers == {"User-Agent": "pytest"}
    assert ticket.request.form_vars == {
        "email": "alice@example.com",
        "password": "<redacted>",
        "callback_data": "<redacted>",
    }
    assert ticket.request.cookies == {"session": "<redacted>"}
    assert ticket.context == context
    ticket_text = ticket_path.read_text(encoding="utf-8")
    assert "secret-token" not in ticket_text
    assert "plaintext-password" not in ticket_text
    assert "eyJhbGciOiJIUzI1NiJ9" not in ticket_text
    assert "abc123" not in ticket_text


def test_ticket_lifecycle_uses_real_files(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """Count, list, delete and delete-all should operate on the stored files."""
    _ticket_env(monkeypatch, tmp_path)
    error_tickets = ErrorTicketService.with_injected()

    first = _raise_and_store_ticket(error_tickets, {"application": "ticket-tests", "seq": 1})
    second = _raise_and_store_ticket(error_tickets, {"application": "ticket-tests", "seq": 2})
    third = _raise_and_store_ticket(error_tickets, {"application": "ticket-tests", "seq": 3})

    assert error_tickets.count() == 3
    assert len(error_tickets.list_tickets()) == 3
    assert len(error_tickets.list_tickets(limit=2)) == 2

    error_tickets.delete(second)
    remaining = error_tickets.list_tickets()
    assert error_tickets.count() == 2
    assert {ticket.meta.ticket_id for ticket in remaining} == {first, third}

    error_tickets.delete_all()
    assert error_tickets.count() == 0
    assert error_tickets.list_tickets() == []
    assert (tmp_path / "errors").exists()


def test_load_ticket_returns_none_for_invalid_toml(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """Malformed ticket files should be ignored rather than crashing."""
    _ticket_env(monkeypatch, tmp_path)
    error_tickets = ErrorTicketService.with_injected()

    bad_ticket_id = "BROKEN-0001"
    bad_path = tmp_path / "errors" / f"{bad_ticket_id}.toml"
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text("not = [valid", encoding="utf-8")

    assert error_tickets.load(bad_ticket_id) is None
