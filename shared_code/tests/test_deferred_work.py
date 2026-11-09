"""Tests for signed deferred-work polling capabilities."""

import uuid
import typing as t
from string.templatelib import Template

import jwt
import pytest

from shared_code.services.deferred import DeferredJob, PgqDeferredWork


class _DeferredResultDatabase:
    """Return predefined PGQ query results in call order."""

    def __init__(self, *query_results: list[tuple[t.Any, ...]]) -> None:
        self.query_results = list(query_results)
        self.queries: list[Template] = []

    def executesql(self, query: Template) -> list[tuple[t.Any, ...]]:
        """Record a query and return its configured result set."""
        self.queries.append(query)
        return self.query_results.pop(0)


@pytest.mark.parametrize(
    ("result_rows", "pending_rows", "expected_status", "expected_value"),
    [
        ([(True, None)], [], "success", None),
        ([(True, b'{"done": true}')], [], "success", {"done": True}),
        ([(False, {"already": "decoded"})], [], "failure", {"already": "decoded"}),
        ([(False, "not-json")], [], "failure", "not-json"),
        ([], [(1,)], "pending", None),
        ([], [], "missing", None),
    ],
)
def test_pgq_deferred_work_resolves_result_states(
    result_rows: list[tuple[t.Any, ...]],
    pending_rows: list[tuple[t.Any, ...]],
    expected_status: str,
    expected_value: t.Any,
) -> None:
    """Stored PGQ results win over queue state, which otherwise distinguishes pending from missing."""
    database = _DeferredResultDatabase(result_rows, pending_rows)
    service = PgqDeferredWork.with_injected(db=database, jwt_key="test-signing-key")
    job = DeferredJob(key=uuid.uuid4(), entrypoint="enhance_vision")

    result = service.result(job)

    assert result.status == expected_status
    assert result.value == expected_value
    assert len(database.queries) == 1 if result_rows else 2


def test_pgq_deferred_work_round_trips_poll_token_context() -> None:
    """A polling token preserves exactly the job reference and caller context it authorises."""
    service = PgqDeferredWork(jwt_key="test-signing-key")
    job = DeferredJob(key=uuid.uuid4(), entrypoint="enhance_vision")

    token = service.create_poll_token(job, {"process_gid": "process-1", "theme": "Rekenen"})
    poll = service.resolve_poll_token(token)

    assert poll.job == job
    assert poll.context == {"process_gid": "process-1", "theme": "Rekenen"}


@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        jwt.encode(
            {
                "aud": "deferred-poll",
                "job_key": str(uuid.uuid4()),
                "entrypoint": "enhance_vision",
                "context": ["not", "a mapping"],
            },
            "test-signing-key",
            algorithm="HS256",
        ),
    ],
)
def test_pgq_deferred_work_rejects_invalid_poll_tokens(token: str) -> None:
    """Malformed claims cannot be used as a polling capability."""
    service = PgqDeferredWork(jwt_key="test-signing-key")

    with pytest.raises(ValueError, match="Invalid deferred polling token"):
        service.resolve_poll_token(token)
