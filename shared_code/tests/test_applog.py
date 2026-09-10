"""Tests for applog service behavior, including end-to-end flow."""

import json
import uuid
from pathlib import Path

from diskcache import Deque
from pytest import MonkeyPatch
from typedal import TypeDAL

from shared_code.modules.auth import AuthAdapter
from shared_code.services.applog import Applogger, DequeApplogger, FileApplogger
from shared_code.services.applog.handler import process_applog_deque


def test_applogger_from_env_fake_uses_file_logger(monkeypatch: MonkeyPatch, tmp_path: Path, db_psql: TypeDAL) -> None:
    """APPLOG_FAKE=1 should select file logger and persist auth events."""
    applog_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("APPLOG_FAKE", "1")
    monkeypatch.setenv("APPLOG_PATH", str(applog_path))

    logger = Applogger.with_injected(db=db_psql, auth_adapter=AuthAdapter.for_service("test.applog.file"))
    assert isinstance(logger, FileApplogger)
    ugid = uuid.uuid4()
    assert logger.log_auth_action(action="login", user_gid=ugid, email="x@example.com", success=True) is True

    rows = [json.loads(line) for line in applog_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["kind"] == "auth_action"
    assert rows[0]["action"] == "login"
    assert rows[0]["user_gid"] == str(ugid)
    assert rows[0]["email"] == "x@example.com"
    assert rows[0]["success"] is True


def test_applogger_from_env_real_uses_deque_logger(monkeypatch: MonkeyPatch, tmp_path: Path, db_psql: TypeDAL) -> None:
    """APPLOG_FAKE=0 should select deque logger and enqueue auth events."""
    deque_dir = tmp_path / "applog-deque"
    monkeypatch.setenv("SERVICE_NAME", "migrate-pytest")
    monkeypatch.setenv("APPLOG_FAKE", "0")
    monkeypatch.setenv("APPLOG_DEQUE_DIR", str(deque_dir))

    logger = Applogger.with_injected(db=db_psql, auth_adapter=AuthAdapter.for_service("test.applog.deque"))
    assert isinstance(logger, DequeApplogger)
    ugid = uuid.uuid4()
    assert logger.log_auth_action(action="logout", user_gid=ugid, email="y@example.com", success=True) is True

    deque = Deque(directory=str(deque_dir))
    payload = json.loads(deque.pop())
    assert payload["name"] == "auth_action"
    assert payload["signal_source"] == "migrate-pytest"
    assert payload["user_gid"] == str(ugid)
    assert payload["session_gid"] is None
    assert not payload.get("related")
    assert payload["evidence"]["action"] == "logout"
    assert payload["evidence"]["email"] == "y@example.com"


def _count_rows(db: TypeDAL, table_name: str) -> int:
    return int(db.executesql(f"SELECT COUNT(*) FROM public.{table_name}")[0][0])


def test_applog_wrapper_to_pgq_consumer_to_db(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """Persist an applog wrapper event all the way through consumer processing."""
    assert migrated_db_per_file is None

    deque_dir = tmp_path / "applog-deque"
    monkeypatch.setenv("APPLOG_FAKE", "0")
    monkeypatch.setenv("APPLOG_DEQUE_DIR", str(deque_dir))

    logger = Applogger.with_injected(db=db_per_file, auth_adapter=AuthAdapter.for_service("test.applog.e2e"))

    assert isinstance(logger, DequeApplogger)

    assert logger.log_auth_action(
        action="login",
        user_gid=uuid.uuid4(),
        email="e2e@example.com",
        success=True,
    )

    # Avoid debounce sleep/refresh side effects while still exercising handler path.
    processed_count = process_applog_deque(db_per_file, batch_size=50)

    assert processed_count == 1

    assert _count_rows(db_per_file, "signal") == 1
    assert _count_rows(db_per_file, "evidence") == 1
