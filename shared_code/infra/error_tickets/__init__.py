"""Persist and retrieve structured error tickets for later inspection."""

import dataclasses as dc
import os
import re
import shutil
import sys
import traceback
import typing as t
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

import configuraptor

from shared_code.data_model import AnyDict
from shared_code.util.time import utcnow

ERROR_CACHE_PATH = Path("/shared_cache") / "errors"
REDACTED_VALUE = "<redacted>"
SAFE_REQUEST_HEADERS = frozenset({"accept", "accept-language", "content-type", "host", "user-agent"})
SENSITIVE_FIELD_NAME = re.compile(
    r"(?:pass(?:word|phrase)?|pwd|secret|token|api[-_]?key|access[-_]?key|"
    r"auth(?:orization)?|cookie|session|csrf|xsrf|otp|mfa|code|credential|"
    r"private[-_]?key|card|cvv|cvc|iban)",
    re.IGNORECASE,
)
SENSITIVE_VALUE = re.compile(
    r"(?:^bearer\s+|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\beyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b|"
    r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b|\bsk_(?:live|test)_[A-Za-z0-9]+\b)",
    re.IGNORECASE,
)


@dc.dataclass
class MetaInfo:
    ticket_id: str
    timestamp: str
    hosting_domain: str
    application: str
    project: str


@dc.dataclass
class RequestInfo:
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
    type: str
    message: str
    traceback: str


@dc.dataclass
class AuthInfo:
    user_email: str = ""
    user_groups: list[str] = dc.field(default_factory=list)


@dc.dataclass
class ErrorTicket:
    """Structured snapshot of an application error."""

    meta: MetaInfo
    request: RequestInfo | None
    exception: ExceptionInfo
    auth: AuthInfo
    context: dict


def _redact_value(name: str, value: t.Any) -> t.Any:
    if SENSITIVE_FIELD_NAME.search(name) or SENSITIVE_VALUE.search(str(value)):
        return REDACTED_VALUE
    return value


def _redact_query_string(query_string: str) -> str:
    if not query_string:
        return ""

    try:
        return urlencode(
            [(name, _redact_value(name, value)) for name, value in parse_qsl(query_string, keep_blank_values=True)]
        )
    except ValueError:
        return REDACTED_VALUE


def redact_request_info(request_info: RequestInfo) -> RequestInfo:
    """Return a diagnostic request snapshot with common credentials removed."""
    return dc.replace(
        request_info,
        query_string=_redact_query_string(request_info.query_string),
        headers={name: value for name, value in request_info.headers.items() if name.lower() in SAFE_REQUEST_HEADERS},
        form_vars={name: _redact_value(name, value) for name, value in request_info.form_vars.items()},
        cookies=dict.fromkeys(request_info.cookies, REDACTED_VALUE),
    )


def _gather_exc_info(context: AnyDict) -> tuple[str, str, str]:
    exc_type_obj, exc_value, tb_obj = sys.exc_info()

    exc_type = exc_type_obj.__name__ if exc_type_obj else context.get("exception_type", "Unknown")
    exc_msg = str(exc_value) if exc_value else context.get("exception", "No message")
    tb_str = (
        "\n".join(traceback.format_exception(exc_type_obj, exc_value, tb_obj))
        if exc_value
        else context.get("traceback", "")
    )

    return exc_type, exc_msg, tb_str


def _gather_py4web_info(_: AnyDict) -> RequestInfo | None:
    try:
        from py4web import request

        return redact_request_info(
            RequestInfo(
                path=request.path,
                method=request.method,
                query_string=request.query_string,
                headers=dict(request.headers),
                form_vars=dict(request.forms),
                cookies=dict(request.cookies),
                remote_addr=request.environ.get("REMOTE_ADDR", "unknown"),
                user_agent=request.headers.get("User-Agent", ""),
            )
        )
    except Exception:
        return None


class SnapshotDict(t.TypedDict):
    auth: AuthInfo | None
    request: RequestInfo | None


def _error_cache_path() -> Path:
    """Return the active error-ticket cache path, creating it if needed."""
    error_cache_path = Path(os.environ.get("ERROR_CACHE_PATH") or ERROR_CACHE_PATH)
    error_cache_path.mkdir(exist_ok=True)
    return error_cache_path


def store_ticket(
    context: AnyDict,
    project: str | None = None,
    snapshot: SnapshotDict | None = None,
) -> str:
    """Write the current error context to disk and return the ticket id."""
    project = (project or os.environ.get("PROJECT", "MISSING-PROJECT")).upper()
    ticket_id = f"{project}-{uuid.uuid7()}"
    error_path = _error_cache_path() / f"{ticket_id}.toml"

    exc_type, exc_msg, tb_str = _gather_exc_info(context)

    req_info = snapshot["request"] if snapshot and "request" in snapshot else _gather_py4web_info(context)
    if req_info:
        req_info = redact_request_info(req_info)
    auth_info = snapshot["auth"] if snapshot else None

    ticket = ErrorTicket(
        meta=MetaInfo(
            ticket_id=ticket_id,
            timestamp=utcnow().isoformat(),
            application=context.get("application", os.environ["APPLICATION_NAME"]),
            hosting_domain=os.environ["HOSTINGDOMAIN"],
            project=os.environ["PROJECT"],
        ),
        request=req_info,
        exception=ExceptionInfo(type=exc_type, message=exc_msg, traceback=tb_str),
        auth=auth_info or AuthInfo(),
        context=context,
    )

    if req_info is None:
        del ticket.request

    error_path.write_text(configuraptor.astoml(ticket))

    return ticket_id


def try_store_ticket(
    context: AnyDict,
    project: str | None = None,
    snapshot: SnapshotDict | None = None,
) -> str | None:
    """Try to store an error ticket, but catch the error and return None instead of a ticket ID on failure."""
    try:
        return store_ticket(context, project=project, snapshot=snapshot)
    except Exception as e:
        print(f"[error-ticket] failed with {type(e)}({e})")
        print("[error-ticket]", "".join(traceback.format_exception(e)))
        return None


def delete_ticket(ticket_id: str) -> None:
    """Delete a single stored error ticket."""
    (_error_cache_path() / f"{ticket_id}.toml").unlink(missing_ok=True)


def delete_all_tickets() -> None:
    """Delete every stored error ticket."""
    error_cache_path = _error_cache_path()
    shutil.rmtree(error_cache_path)
    error_cache_path.mkdir(exist_ok=True)


def list_tickets(limit: int = 0) -> list[ErrorTicket]:
    """Return all stored error tickets in descending file order."""
    tickets: list[ErrorTicket] = []
    for filepath in sorted(_error_cache_path().glob("*.toml"), reverse=True):
        ticket_id = filepath.name.removesuffix(".toml")
        if ticket := load_ticket(ticket_id):
            tickets.append(ticket)

        if limit and len(tickets) >= limit:
            break

    return tickets


def count_tickets() -> int:
    """Return the number of stored error tickets."""
    return len(list(_error_cache_path().glob("*.toml")))


def load_ticket(ticket_id: str) -> ErrorTicket | None:
    """Load a stored ticket by id, returning ``None`` if it cannot be parsed."""
    try:
        return configuraptor.load_into(ErrorTicket, _error_cache_path() / f"{ticket_id}.toml")
    except Exception as e:
        print("Failed loading error ticket:", e)
        return None


__all__ = [
    "ErrorTicket",
    "count_tickets",
    "delete_all_tickets",
    "delete_ticket",
    "list_tickets",
    "load_ticket",
    "redact_request_info",
    "store_ticket",
    "try_store_ticket",
]
