"""PGQ-backed implementation of deferred work."""

import datetime as dt
import json
import typing as t
import uuid
from pathlib import Path

import jwt
from pgskewer.helpers import queue_job

from shared_code.data_model import AnyDict, AnyMapping

from ...util.time import utcnow
from .contracts import DeferredJob, DeferredPoll, DeferredResult, DeferredWork

POLL_TOKEN_AUDIENCE = "deferred-poll"  # noqa S105: not a password just an 'aud'
POLL_TOKEN_LIFETIME = dt.timedelta(minutes=10)

if t.TYPE_CHECKING:
    from shared_code.infra.database import DatabaseContext


class PgqDeferredWork(DeferredWork):
    """Store deferred work and resolve its state through PGQ tables."""

    db: DatabaseContext

    def __init__(self, jwt_key: str) -> None:
        """Configure the key used to sign polling capabilities."""
        self.jwt_key = jwt_key

    def enqueue(self, entrypoint: str, payload: AnyMapping) -> DeferredJob:
        """Queue one JSON payload and return its stable PGQ dedupe key."""
        queued = queue_job(self.db, entrypoint, t.cast(AnyDict, payload), dill=True)
        return DeferredJob(key=queued.key, entrypoint=entrypoint)

    def result(self, job: DeferredJob) -> DeferredResult:
        """Resolve a stored result first, then distinguish pending from missing work."""
        result_rows = self.db.executesql(
            t"""
            SELECT ok, result
            FROM pgqueuer_result
            WHERE unique_key = {job.key}
              AND entrypoint = {job.entrypoint}
            LIMIT 1;
            """
        )
        if result_rows:
            ok, raw_result = result_rows[0]
            return DeferredResult(
                status="success" if ok else "failure",
                value=self._decode_result(raw_result),
            )

        pending_rows = self.db.executesql(
            t"""
            SELECT 1
            FROM pgqueuer
            WHERE dedupe_key = {job.key}
              AND entrypoint = {job.entrypoint}
            LIMIT 1;
            """,
        )
        return DeferredResult(status="pending" if pending_rows else "missing")

    def create_poll_token[ContextT: AnyMapping](self, job: DeferredJob, context: ContextT) -> str:
        """Create a short-lived signed capability for polling one deferred job."""
        return jwt.encode(
            {
                "aud": POLL_TOKEN_AUDIENCE,
                "context": context,
                "entrypoint": job.entrypoint,
                "exp": utcnow() + POLL_TOKEN_LIFETIME,
                "job_key": str(job.key),
            },
            self.jwt_key,
            algorithm="HS256",
        )

    def resolve_poll_token[ContextT: AnyMapping](self, token: str) -> DeferredPoll[ContextT]:
        """Validate a polling capability and recover its job and signed context."""
        try:
            claims = jwt.decode(
                token,
                self.jwt_key,
                algorithms=["HS256"],
                audience=POLL_TOKEN_AUDIENCE,
            )
            job_key = claims["job_key"]
            entrypoint = claims["entrypoint"]
            context = claims["context"]
            if not isinstance(job_key, str) or not isinstance(entrypoint, str) or not isinstance(context, dict):
                raise ValueError("Invalid deferred polling token.")
            job = DeferredJob(key=uuid.UUID(job_key), entrypoint=entrypoint)
        except (jwt.InvalidTokenError, KeyError, ValueError) as exc:
            raise ValueError("Invalid deferred polling token.") from exc
        return DeferredPoll[ContextT](job=job, context=context)

    @staticmethod
    def _decode_result(raw_result: object) -> object | None:
        """Decode PGQ's JSON result while preserving unexpected stored values."""
        if raw_result is None:
            return None
        elif isinstance(raw_result, bytes):
            raw_result = raw_result.decode()
        elif not isinstance(raw_result, str):
            return raw_result

        try:
            return json.loads(raw_result)
        except TypeError, ValueError:
            return raw_result

    @classmethod
    def from_env(cls) -> DeferredWork:
        """Return simple instance; dependencies like 'db' are managed by endow via 'with_injected()'."""
        return cls(jwt_key=Path("/shared_keys/jwt.key").read_text())
