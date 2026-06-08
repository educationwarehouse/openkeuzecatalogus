"""Mail service package."""

from .contracts import Mailer
from .fake import MockMailer
from .smtp import SMTPMailer

__all__ = [
    "Mailer",
    "MockMailer",
    "SMTPMailer",
]
