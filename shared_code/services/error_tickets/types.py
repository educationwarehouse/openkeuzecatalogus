"""Structured data used by the error-ticket service."""

import dataclasses as dc
import re
import typing as t
from urllib.parse import parse_qsl, urlencode

from shared_code.data_model import AnyMapping

REDACTED_VALUE = "<redacted>"
SAFE_REQUEST_HEADERS = frozenset(("accept", "accept-language", "content-type", "host", "user-agent"))
SENSITIVE_FIELD_NAME = re.compile(
    r"(?:pass(?:word|phrase)?|pwd|secret|token|api[-_]?key|access[-_]?key|"
    r"auth(?:orization)?|cookie|session|csrf|xsrf|otp|mfa|code|credential|"
    r"private[-_]?key|card|cvv|cvc|iban|signature)",
    re.IGNORECASE,
)
SENSITIVE_VALUE = re.compile(
    r"(?:^bearer\s+|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\beyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b|"
    r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b|\bsk_(?:live|test)_[A-Za-z0-9]+\b)",
    re.IGNORECASE,
)
EMAIL_FIELD_NAME = re.compile(r"e[-_]?mail", re.IGNORECASE)
EMAIL_VALUE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


@dc.dataclass
class MetaInfo:
    """Metadata identifying and locating an error ticket."""

    ticket_id: str
    timestamp: str
    hosting_domain: str
    application: str
    project: str


@dc.dataclass
class RequestInfo:
    """Safe snapshot of the request that triggered an error."""

    path: str
    method: str
    query_string: str
    headers: dict
    form_vars: dict
    cookies: dict
    remote_addr: str
    user_agent: str


@dc.dataclass
class ExceptionInfo:
    """Captured exception details for an error ticket."""

    type: str
    message: str
    traceback: str


@dc.dataclass
class AuthInfo:
    """Authenticated-user information associated with an error."""

    user_email: str = ""
    user_groups: list[str] = dc.field(default_factory=list)


@dc.dataclass
class ErrorTicket:
    """Structured snapshot of an application error."""

    meta: MetaInfo
    request: RequestInfo | None
    exception: ExceptionInfo
    auth: AuthInfo
    context: AnyMapping


class SnapshotDict(t.TypedDict):
    """Request-scoped data captured before error rendering."""

    auth: AuthInfo | None
    request: RequestInfo | None


def redact_value(name: str, value: t.Any) -> t.Any:
    """Remove common credentials from one diagnostic field, preserving email addresses."""
    if SENSITIVE_FIELD_NAME.search(name) or SENSITIVE_VALUE.search(str(value)):
        return REDACTED_VALUE

    return value


def redact_query_params(params: t.Mapping[str, t.Any] | None) -> dict[str, str]:
    """Normalize route-statistics parameters, removing credentials and email addresses."""
    redacted = {}
    for key, value in sorted((params or {}).items()):
        name = str(key)
        if EMAIL_FIELD_NAME.search(name) or EMAIL_VALUE.search(str(value)):
            redacted[name] = REDACTED_VALUE
        else:
            redacted[name] = str(redact_value(name, value))
    return redacted


def _redact_query_string(query_string: str) -> str:
    if not query_string:
        return ""

    try:
        return urlencode(
            [(name, redact_value(name, value)) for name, value in parse_qsl(query_string, keep_blank_values=True)]
        )
    except ValueError:
        return REDACTED_VALUE


def redact_request_info(request_info: RequestInfo) -> RequestInfo:
    """Return a diagnostic request snapshot with common credentials removed."""
    return dc.replace(
        request_info,
        query_string=_redact_query_string(request_info.query_string),
        headers={name: value for name, value in request_info.headers.items() if name.lower() in SAFE_REQUEST_HEADERS},
        form_vars={name: redact_value(name, value) for name, value in request_info.form_vars.items()},
        cookies=dict.fromkeys(request_info.cookies, REDACTED_VALUE),
    )
