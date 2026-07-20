"""Fake mail service implementations for testing."""

import json
import os
import typing as t
from email.message import EmailMessage
from pathlib import Path

from shared_code.services.mail.contracts import EmailAddress, Mailer


class MockMailer(Mailer):
    """Test mailer that appends delivered emails to a JSONL inbox file."""

    def __init__(self, inbox_path: Path) -> None:
        """Initialize the fake mailer with the path of the JSONL inbox."""
        self.inbox_path = inbox_path
        self.sender = "mock@localhost"

    def send_email_message(self, message: EmailMessage, all_recipients: list[EmailAddress]) -> bool:
        """Serialize and persist a mail payload line for test assertions."""
        self.inbox_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            text_part = message.get_body(preferencelist=("plain",))
            html_part = message.get_body(preferencelist=("html",))
            payload = {
                "headers": dict(message.items()),
                "subject": message.get("Subject"),
                "from": message.get("From"),
                "to": message.get("To"),
                "cc": message.get("Cc"),
                "reply_to": message.get("Reply-To"),
                "all_recipients": all_recipients,
                "text_body": text_part.get_content() if text_part is not None else None,
                "html_body": html_part.get_content() if html_part is not None else None,
            }
        except Exception as e:
            print(f"[email] failed: {e}")
            return False

        print(f"[email] {payload}")
        with self.inbox_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, ensure_ascii=True))
            fp.write("\n")

        return True

    @classmethod
    def from_env(cls) -> t.Self:
        """Create a fake mailer using environment-configured inbox path."""
        inbox_path = Path(os.environ.get("SMTP_FAKE_INBOX_PATH", "/shared_cache/mail/mock_inbox.jsonl"))
        return cls(inbox_path=inbox_path)
