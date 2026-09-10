"""Mail service contracts."""

import abc
import typing as t
import warnings
from email.message import EmailMessage

from endow import Service
from pgskewer.helpers import EnqueuedJob, queue_job

from shared_code.services.error_tickets import ErrorTicketService
from shared_code.util.env import bool_from_env

if t.TYPE_CHECKING:
    # noinspection PyUnusedImports
    from py4web.utils.mailer import Mailer as Py4webMailer

    from shared_code.infra.database import DatabaseContext


type EmailAddress = str
type Recipients = EmailAddress | t.Sequence[EmailAddress]
type BodyPart = str | bytes | t.IO[t.Any] | None
type Body = BodyPart | tuple[BodyPart, BodyPart] | list[BodyPart]
type Attachments = "Py4webMailer.Attachment | str | t.Sequence[Py4webMailer.Attachment] | t.Sequence[str] | None"


class QueuedEmail(t.TypedDict):
    """Serialized payload for deferred email delivery jobs."""

    message: EmailMessage
    all_recipients: list[EmailAddress]


class Mailer(Service, abc.ABC):
    """Abstract mailer contract plus shared message construction helpers."""

    db: DatabaseContext
    error_tickets: ErrorTicketService

    # start contract to be implemented
    sender: str

    @abc.abstractmethod
    def send_email_message(self, message: EmailMessage, all_recipients: list[EmailAddress]) -> bool:
        """Deliver a fully prepared email message to all recipients."""
        ...

    # end contract

    # start generic implementation details

    def send(
        self,
        to: Recipients,
        subject: str = "[no subject]",
        body: Body = "[no body]",
        sender: EmailAddress | None = None,
        cc: Recipients | None = None,
        bcc: Recipients | None = None,
        reply_to: EmailAddress | None = None,
        encoding: str = "utf-8",
        raw: bool = False,
        headers: t.Mapping[str, str] | None = None,
        from_address: EmailAddress | None = None,
        # dkim: t.Any = None,
        # list_unsubscribe: EmailAddress | None = None,
        # cipher_type: str | None = None,
        # sign: bool | None = None,
        # sign_passphrase: str | None = None,
        # encrypt: bool | None = None,
        # x509_sign_keyfile: str | None = None,
        # x509_sign_chainfile: str | None = None,
        # x509_sign_certfile: str | None = None,
        # x509_crypt_certfiles: str | t.Sequence[str] | None = None,
        # x509_nocerts: bool | None = None,
        blocking: bool = False,
        **_: t.Any,
    ) -> bool:
        """Build and send an email, returning `True` on successful delivery."""
        if _:
            warnings.warn(f"passed ignored attributes to Mailer.send: {_}", stacklevel=2)

        recipients = self._to_list(to)
        cc_list = self._to_list(cc)
        bcc_list = self._to_list(bcc)

        all_recipients = recipients + cc_list + bcc_list

        message = self.build_message(
            recipients=recipients,
            subject=subject,
            body=body,
            sender=sender,
            cc_list=cc_list,
            reply_to=reply_to,
            encoding=encoding,
            raw=raw,
            headers=headers,
            from_address=from_address,
        )
        if not (message and all_recipients):
            return False

        if blocking:
            return self.send_email_message(message, all_recipients=all_recipients)
        else:
            self.enqueue_email_message(message, all_recipients=all_recipients)
            return True

    def enqueue_email_message(self, message: EmailMessage, all_recipients: list[EmailAddress]) -> EnqueuedJob:
        """Enqueue delivery of a fully prepared email message to all recipients."""
        return queue_job(
            self.db,
            "send_email_message",
            payload={
                "message": message,
                "all_recipients": all_recipients,
            },
            dill=True,
        )

    @classmethod
    def from_env(cls) -> Mailer:
        """Instantiate the configured mail transport from environment variables."""
        if bool_from_env("SMTP_FAKE", True):
            from .fake import MockMailer

            return MockMailer.from_env()
        else:
            from .smtp import SMTPMailer

            return SMTPMailer.from_env()

    def build_message(
        self,
        recipients: list[EmailAddress],
        cc_list: list[EmailAddress],
        subject: str = "[no subject]",
        body: Body = "[no body]",
        sender: EmailAddress | None = None,
        reply_to: EmailAddress | None = None,
        encoding: str = "utf-8",
        raw: bool = False,
        headers: t.Mapping[str, str] | None = None,
        from_address: EmailAddress | None = None,
    ) -> EmailMessage | None:
        """Create an `EmailMessage` object from normalized sender/body inputs."""
        envelope_sender = sender or self.sender or from_address
        if not envelope_sender:
            return None

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = from_address or envelope_sender
        message["To"] = ", ".join(recipients)
        if cc_list:
            message["Cc"] = ", ".join(cc_list)
        if reply_to:
            message["Reply-To"] = reply_to
        for key, value in (headers or {}).items():
            message[key] = value

        if raw:
            message.set_content(self._read_body_part(body, encoding) or "")
        else:
            text_body, html_body = self._split_body(body, encoding)
            if text_body is not None:
                message.set_content(text_body)
            if html_body is not None:
                if text_body is None:
                    message.set_content("")
                message.add_alternative(html_body, subtype="html")
            if text_body is None and html_body is None:
                message.set_content("")

        return message

    @staticmethod
    def _to_list(recipients: Recipients | None) -> list[str]:
        if recipients is None:
            return []
        if isinstance(recipients, str):
            return [recipients]
        return [str(value) for value in recipients]

    @staticmethod
    def _read_body_part(part: t.Any, encoding: str = "utf-8") -> str | None:
        if part is None:
            return None
        if hasattr(part, "read") and callable(part.read):
            part = part.read()
        if isinstance(part, bytes):
            return part.decode(encoding, errors="replace")
        return str(part)

    @classmethod
    def _split_body(cls, body: Body, encoding: str = "utf-8") -> tuple[str | None, str | None]:
        if isinstance(body, tuple | list):
            parts = [cls._read_body_part(part, encoding) for part in body]
            text = parts[0] if len(parts) > 0 else None
            html = parts[1] if len(parts) > 1 else None
            return text, html
        return cls._read_body_part(body, encoding), None
