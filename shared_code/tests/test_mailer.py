"""Tests for mailer behavior."""

import json
import typing as t
from pathlib import Path

from shared_code.modules.auth import AuthAdapter
from typedal import TypeDAL

from shared_code.services.mail import Mailer, MockMailer, SMTPMailer

if t.TYPE_CHECKING:
    from pytest import MonkeyPatch

MOCK_INBOX_PATH = Path("/shared_cache/mail/mock_inbox.jsonl")


def test_mailer_uses_fake_sender_and_writes_inbox(db_psql: TypeDAL) -> None:
    """When SMTP_FAKE is enabled in runner env, mails are written to the JSONL inbox."""
    sender = Mailer.with_injected(db=db_psql)
    assert isinstance(sender, MockMailer)

    sent = sender.send(
        to="mailtest@example.com",
        subject="registration verification",
        body="hello from shared_code test",
        sender="noreply@example.com",
        blocking=True,
    )
    assert sent is True
    assert MOCK_INBOX_PATH.exists()

    rows = [json.loads(line) for line in MOCK_INBOX_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    message = rows[0]
    assert message["subject"] == "registration verification"
    assert message["from"] == "noreply@example.com"
    assert "mailtest@example.com" in message["all_recipients"]
    assert "hello from shared_code test" in (message["text_body"] or "")


def test_smtp_mailer_from_env_splits_host_and_port(monkeypatch: MonkeyPatch, db_psql: TypeDAL) -> None:
    """SMTP server env may include host:port and should split correctly."""
    monkeypatch.setenv("SMTP_FAKE", "0")
    monkeypatch.setenv("SMTP_SERVER", "smtp.example.com:2525")
    monkeypatch.delenv("SMTP_PORT", raising=False)
    monkeypatch.setenv("SMTP_USER", "mailer@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_TLS", "1")
    monkeypatch.setenv("SMTP_SSL", "0")

    mailer = Mailer.with_injected(
        auth_adapter=AuthAdapter.for_service("pytest.smtp_mailer")
    )

    assert isinstance(mailer, SMTPMailer)

    assert mailer.host == "smtp.example.com"
    assert mailer.port == 2525
    assert mailer.user == "mailer@example.com"
    assert mailer.password == "secret"
    assert mailer.sender == "mailer@example.com"
    assert mailer.tls is True
    assert mailer.ssl is False


def test_smtp_mailer_from_env_with_incomplete_config_raises_oserror(monkeypatch: MonkeyPatch, db_psql: TypeDAL) -> None:
    """Missing required SMTP values should raise an incomplete-config OSError."""
    monkeypatch.setenv("SMTP_SERVER", "smtp.example.com:587")
    monkeypatch.setenv("SMTP_USER", "mailer@example.com")
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)

    try:
        SMTPMailer.from_env() # noqa: EW002 - this is on purpose
    except OSError as exc:
        assert str(exc) == "Incomplete SMTP Config"
    else:  # pragma: no cover
        raise AssertionError("Expected OSError for incomplete SMTP config")


def test_mailer_from_env_stores_ticket_when_smtp_delivery_fails(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """The contract factory must safely handle SMTP transport errors."""
    error_cache_path = tmp_path / "errors"
    monkeypatch.setenv("SMTP_FAKE", "0")
    monkeypatch.setenv("SMTP_SERVER", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "65536")
    monkeypatch.setenv("SMTP_USER", "mailer@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_TLS", "0")
    monkeypatch.setenv("SMTP_SSL", "0")
    monkeypatch.setenv("APPLICATION_NAME", "mailer-tests")
    monkeypatch.setenv("HOSTINGDOMAIN", "example.test")
    monkeypatch.setenv("PROJECT", "tests")
    monkeypatch.setenv("PROJECT", "tests")
    monkeypatch.setenv("ERROR_CACHE_PATH", str(error_cache_path))
    monkeypatch.setenv("ERROR_SIGNAL_QUEUE_PATH", str(tmp_path / "error-signals"))

    mailer = Mailer.with_injected(
        auth_adapter=AuthAdapter.for_service("pytest.mailer"),
    )
    assert isinstance(mailer, SMTPMailer), "wrong mailer selected"

    sent = mailer.send(
        to="recipient@example.com",
        subject="failed delivery",
        body="This must create an error ticket.",
        blocking=True,
    )

    assert sent is False
    assert len(list(error_cache_path.glob("*.toml"))) == 1


def test_mock_mailer_writes_tuple_body_reply_to_cc_and_headers(tmp_path: Path, db_psql: TypeDAL) -> None:
    """Mock mail payload should include multipart body metadata and extra headers."""
    inbox_path = tmp_path / "mock_inbox.jsonl"
    mailer = MockMailer(inbox_path=inbox_path)

    sent = mailer.send(
        to=["to1@example.com", "to2@example.com"],
        subject="complex payload",
        body=("Plain text body", "<p>HTML body</p>"),
        sender="noreply@example.com",
        cc=["cc1@example.com", "cc2@example.com"],
        bcc=["bcc@example.com"],
        reply_to="helpdesk@example.com",
        headers={"X-Trace-Id": "trace-123", "X-Environment": "test"},
        blocking=True,
    )

    assert sent is True
    rows = [json.loads(line) for line in inbox_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1

    message = rows[0]
    assert message["subject"] == "complex payload"
    assert message["from"] == "noreply@example.com"
    assert message["to"] == "to1@example.com, to2@example.com"
    assert message["cc"] == "cc1@example.com, cc2@example.com"
    assert message["reply_to"] == "helpdesk@example.com"
    assert "Plain text body" in (message["text_body"] or "")
    assert "<p>HTML body</p>" in (message["html_body"] or "")
    assert "to1@example.com" in message["all_recipients"]
    assert "to2@example.com" in message["all_recipients"]
    assert "cc1@example.com" in message["all_recipients"]
    assert "cc2@example.com" in message["all_recipients"]
    assert "bcc@example.com" in message["all_recipients"]
    assert message["headers"]["X-Trace-Id"] == "trace-123"
    assert message["headers"]["X-Environment"] == "test"
