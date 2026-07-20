"""SMTP-related helper functions."""

import os
import smtplib
import typing as t
from email.message import EmailMessage

from shared_code.services.mail.contracts import EmailAddress, Mailer
from shared_code.util.env import bool_from_env


class SMTPMailer(Mailer):
    """SMTP-backed mailer implementation for real email delivery."""

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        sender: EmailAddress | None = None,
        tls: bool = True,
        ssl: bool = False,
    ) -> None:
        """Store SMTP connection settings used for outbound email delivery."""
        self.host = host
        self.port = port
        self.sender = sender or user
        self.user = user
        self.password = password
        self.tls = tls
        self.ssl = ssl

    def send_email_message(self, message: EmailMessage, all_recipients: list[EmailAddress]) -> bool:
        """Send a prepared email via SMTP and report success as a boolean."""
        smtp_class = smtplib.SMTP_SSL if self.ssl else smtplib.SMTP
        try:
            with smtp_class(self.host, self.port, timeout=5) as server:
                if self.tls and not self.ssl:
                    server.starttls()

                server.login(self.user, self.password or "")
                server.send_message(message, from_addr=message["From"], to_addrs=all_recipients)
                return True
        except Exception:
            return False

    @classmethod
    def from_env(cls) -> t.Self:
        """Create an SMTP mailer instance from environment variables."""
        server = os.environ.get("SMTP_SERVER", "")
        port = int(os.environ.get("SMTP_PORT") or "587")
        if ":" in server:
            host, server_port = server.rsplit(":", 1)
            server = host
            if "SMTP_PORT" not in os.environ:
                port = int(server_port)

        user = os.environ.get("SMTP_USER")
        password = os.environ.get("SMTP_PASSWORD")

        if not (server and user and password):
            raise OSError("Incomplete SMTP Config")

        return cls(
            host=server,
            port=port,
            sender=os.environ.get("SMTP_SENDER"),
            user=user,
            password=password,
            tls=bool_from_env("SMTP_TLS", default=False),
            ssl=bool_from_env("SMTP_SSL", default=False),
        )
