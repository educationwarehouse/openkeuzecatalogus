"""Capture request-scoped error ticket data before py4web tears fixtures down."""

from contextvars import ContextVar

from py4web.core import Fixture

from py4web import request
from shared_code.data_model import AnyDict
from shared_code.services.error_tickets import AuthInfo, RequestInfo, SnapshotDict, redact_request_info


class ErrorTicketHelper(Fixture):
    """Snapshot auth and request data during `on_error` for later ticket rendering."""

    _snapshot: ContextVar[SnapshotDict | None] = ContextVar("error_ticket_snapshot", default=None)

    def on_request(self, context: AnyDict) -> None:
        """Clear the cached snapshot before the next request starts."""
        self._snapshot.set(None)

    def on_error(self, context: AnyDict) -> None:
        """Capture request and auth data when the request fails."""
        self._snapshot.set(SnapshotDict(auth=self._snapshot_auth_info(), request=self._snapshot_request_info()))

    def on_success(self, context: AnyDict) -> None:
        """Drop any snapshot after a successful request."""
        self.teardown()

    @staticmethod
    def _snapshot_auth_info() -> AuthInfo:
        from common.models import auth_context

        if not (user := auth_context.user):
            return AuthInfo()

        try:
            user_groups = auth_context.roles
        except Exception:
            # runs before the db fixture rolls back, so a failed transaction can't answer role queries;
            # the error page then re-checks admin access after rollback.
            user_groups = []

        return AuthInfo(user_email=user.email or "", user_groups=user_groups)

    @staticmethod
    def _snapshot_request_info() -> RequestInfo:
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

    def peek(self) -> SnapshotDict | None:
        """Return the currently cached snapshot without consuming it."""
        return self._snapshot.get()

    def consume(self) -> SnapshotDict | None:
        """Return the cached snapshot and clear it."""
        snapshot = self.peek()
        self.teardown()
        return snapshot

    def teardown(self) -> None:
        """Clear the cached snapshot."""
        self._snapshot.set(None)


error_ticket_helper = ErrorTicketHelper()


__all__ = [
    "ErrorTicketHelper",
    "error_ticket_helper",
]
