"""File-backed implementation of the error-ticket service."""

import os
import shutil
import sys
import traceback
import typing as t
import uuid
from pathlib import Path

import configuraptor
from endow import Service

from shared_code.data_model import AnyDict
from shared_code.infra.web import PY4WEB_URL
from shared_code.services.error_signals import ErrorSignal, ErrorSignalService
from shared_code.util.time import utcnow

from .constants import ERROR_CACHE_PATH
from .types import AuthInfo, ErrorTicket, ExceptionInfo, MetaInfo, RequestInfo, SnapshotDict, redact_request_info


class ErrorTicketService(Service):
    """Persist and retrieve structured error tickets from the shared cache."""

    signals: ErrorSignalService

    @staticmethod
    def _error_cache_path() -> Path:
        """Return the active error-ticket cache path, creating it if needed."""
        error_cache_path = Path(os.environ.get("ERROR_CACHE_PATH") or ERROR_CACHE_PATH)
        error_cache_path.mkdir(exist_ok=True)
        return error_cache_path

    @staticmethod
    def _gather_exc_info(context: AnyDict) -> tuple[str, str, str]:
        """Capture the active exception, falling back to the supplied context."""
        exc_type_obj, exc_value, tb_obj = sys.exc_info()
        exc_type = exc_type_obj.__name__ if exc_type_obj else context.get("exception_type", "Unknown")
        exc_msg = str(exc_value) if exc_value else context.get("exception", "No message")
        tb_str = (
            "\n".join(traceback.format_exception(exc_type_obj, exc_value, tb_obj))
            if exc_value
            else context.get("traceback", "")
        )
        return exc_type, exc_msg, tb_str

    @staticmethod
    def _gather_py4web_info() -> RequestInfo | None:
        """Capture and redact the current py4web request when available."""
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

    def store(
        self,
        context: AnyDict,
        project: str | None = None,
        snapshot: SnapshotDict | None = None,
    ) -> str:
        """Write the current error context to disk and return the ticket id."""
        project = (project or os.environ.get("PROJECT", "MISSING-PROJECT")).upper()
        ticket_id = f"{project}-{uuid.uuid7()}"
        error_path = self._error_cache_path() / f"{ticket_id}.toml"
        exc_type, exc_msg, tb_str = self._gather_exc_info(context)
        req_info = snapshot["request"] if snapshot and "request" in snapshot else self._gather_py4web_info()
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
        try:
            self.enqueue_ticket_signal(ticket)
        except Exception as error:
            print(f"[error-ticket] failed to queue signal: {type(error).__name__}({error})")
        return ticket_id

    def try_store(
        self,
        context: AnyDict,
        project: str | None = None,
        snapshot: SnapshotDict | None = None,
    ) -> str | None:
        """Try to store an error ticket without letting storage failures escape."""
        try:
            return self.store(context, project=project, snapshot=snapshot)
        except Exception as error:
            print(f"[error-ticket] failed with {type(error)}({error})")
            print("[error-ticket]", "".join(traceback.format_exception(error)))
            return None

    def delete(self, ticket_id: str) -> None:
        """Delete a single stored error ticket."""
        (self._error_cache_path() / f"{ticket_id}.toml").unlink(missing_ok=True)

    def delete_all(self) -> None:
        """Delete every stored error ticket."""
        error_cache_path = self._error_cache_path()
        shutil.rmtree(error_cache_path)
        error_cache_path.mkdir(exist_ok=True)

    def list_tickets(self, limit: int = 0, ticket_ids: t.Collection[str] | None = None) -> list[ErrorTicket]:
        """Return stored error tickets in descending file order, optionally by ID."""
        tickets: list[ErrorTicket] = []
        selected_ticket_ids = set(ticket_ids) if ticket_ids is not None else None
        for filepath in sorted(self._error_cache_path().glob("*.toml"), reverse=True):
            ticket_id = filepath.name.removesuffix(".toml")
            if selected_ticket_ids is not None and ticket_id not in selected_ticket_ids:
                continue
            if ticket := self.load(ticket_id):
                tickets.append(ticket)
            if limit and len(tickets) >= limit:
                break
        return tickets

    def count(self) -> int:
        """Return the number of stored error tickets."""
        return len(list(self._error_cache_path().glob("*.toml")))

    def load(self, ticket_id: str) -> ErrorTicket | None:
        """Load a stored ticket by id, returning `None` if it cannot be parsed."""
        try:
            return configuraptor.load_into(ErrorTicket, self._error_cache_path() / f"{ticket_id}.toml")
        except Exception as error:
            print("[error-ticket] failed loading ticket:", error)
            return None

    # signals

    def enqueue_ticket_signal(self, ticket: ErrorTicket) -> None:
        """Queue a safe ticket summary without delaying the erroring caller."""
        self.signals.enqueue(
            ErrorSignal(
                ticket_id=ticket.meta.ticket_id,
                project=ticket.meta.project,
                application=ticket.meta.application,
                timestamp=ticket.meta.timestamp,
                exception_type=ticket.exception.type,
                exception_message=ticket.exception.message,
                click_url=PY4WEB_URL("admin", "errors", ticket.meta.ticket_id),
            )
        )

    def process_ticket_signal_queue(self, batch_size: int = 50) -> int:
        """Deliver queued signals without creating a new ticket on failure."""
        return self.signals.process_queue(batch_size)
