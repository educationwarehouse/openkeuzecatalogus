"""Tests for the admin audit-log grid helpers."""

import uuid
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager

import pytest
from apps.admin.models.audit_logs import (
    _audit_filter_pills,
    _audit_filter_value,
    _audit_log_query,
    _user_association_query,
)

from shared_code.data_model import Evidence, Signal


def _all_signal_ids() -> str:
    """Return the subquery used to make audit filters executable in tests."""
    return Signal.where(Signal.id > 0).select(Signal.id).to_sql()


def test_audit_filter_value_does_not_link_missing_gid() -> None:
    """Missing GIDs render as plain text rather than a link to `None`."""
    assert _audit_filter_value("user_gid", None) == "-"


@pytest.mark.parametrize("parameter", ["session_gid", "user_gid"])
def test_audit_log_query_ignores_invalid_gid_filters(
    admin_app_request_context: None,
    request_query: Callable[[Mapping[str, str]], AbstractContextManager[None]],
    parameter: str,
) -> None:
    """Malformed GID filters never reach the UUID columns in PostgreSQL."""
    with request_query({parameter: "None"}):
        assert Signal.where(_audit_log_query(_all_signal_ids())).select(Signal.id).collect() is not None


@pytest.mark.parametrize("parameter", ["session_gid", "user_gid"])
def test_audit_log_query_applies_valid_gid_filters(
    admin_app_request_context: None,
    request_query: Callable[[Mapping[str, str]], AbstractContextManager[None]],
    parameter: str,
) -> None:
    """Valid GID filters remain part of the audit-log query."""
    gid = str(uuid.uuid4())
    signal = Signal.insert(
        name="audit-log-test",
        source="pytest",
        **{parameter: gid},
    )

    with request_query({parameter: gid}):
        matching_signals = Signal.where(_audit_log_query(_all_signal_ids())).select(Signal.gid).collect()

    assert signal.gid in {row.gid for row in matching_signals}


def test_audit_log_query_matches_user_associations_in_evidence(
    admin_app_request_context: None,
    request_query: Callable[[Mapping[str, str]], AbstractContextManager[None]],
) -> None:
    """The broad user filter includes related signals and nested evidence GIDs."""
    user_gid = str(uuid.uuid4())
    association_sources = (
        {"user_gid": user_gid},
        {"details": {"target_user_gid": user_gid}},
        {"details": {"subject_gid": user_gid}},
        {"details": {"user_gid": user_gid}},
        {"details": {"related_gid": user_gid}},
    )
    matching_signals = [
        Signal.insert(
            name="audit-log-test",
            source="pytest",
            evidence_id=Evidence.insert(source=source, sha1_digest=uuid.uuid4().hex).id,
        )
        for source in association_sources
    ]
    matching_signals.append(Signal.insert(name="audit-log-test", source="pytest", related=user_gid))
    unrelated_signal = Signal.insert(name="audit-log-test", source="pytest", user_gid=str(uuid.uuid4()))

    with request_query({"user": user_gid}):
        results = Signal.where(_audit_log_query(_all_signal_ids())).select(Signal.gid).collect()

    result_gids = {row.gid for row in results}
    assert {signal.gid for signal in matching_signals} <= result_gids
    assert unrelated_signal.gid not in result_gids


def test_user_association_query_renders_missing_email_as_sql_null(admin_app_request_context: None) -> None:
    """A missing user email disables email matching without rendering the string `None`."""
    query_sql = Signal.where(_user_association_query(str(uuid.uuid4()), None)).select(Signal.id).to_sql()

    assert "NULL IS NOT NULL" in query_sql
    assert "'None' IS NOT NULL" not in query_sql


def test_audit_filter_pill_clears_only_its_own_filter(
    admin_app_request_context: None,
    request_query: Callable[[Mapping[str, str]], AbstractContextManager[None]],
) -> None:
    """A filter pill keeps the page-size setting while removing its filter."""
    with request_query(
        {
            "user_gid": str(uuid.uuid4()),
            "audit_log_limit": "500",
        }
    ):
        pills = str(_audit_filter_pills())

    assert "User GID:" in pills
    assert "audit_log_limit=500" in pills
    assert "user_gid=" not in pills
