"""Tests for the shared file-backed cache helper."""

import time
from pathlib import Path

from common.fixtures.flag_based_cache import FlagBasedCache


def test_flag_based_cache_reports_missing_flag_as_fresh(tmp_path: Path) -> None:
    """A missing flag file should be treated as a fresh cache."""
    cache = FlagBasedCache(tmp_path / "cache.flag", lambda: {"value": 1})

    assert cache.is_stale() is False


def test_flag_based_cache_callable_reloads_when_flag_changes(tmp_path: Path) -> None:
    """Callable-backed caches should reload once the flag file changes."""
    flag_file = tmp_path / "cache.flag"
    calls: list[int] = []

    def loader() -> dict[str, int]:
        calls.append(len(calls) + 1)
        return {"load": len(calls)}

    cache = FlagBasedCache(flag_file, loader)

    first = cache.get()
    second = cache.get()

    assert first == {"load": 1}
    assert second is first
    assert calls == [1]

    time.sleep(0.1)  # ensure the filesystem mtime advances before rechecking
    flag_file.touch()

    assert cache.is_stale() is True

    reloaded = cache.get()
    assert reloaded == {"load": 2}
    assert reloaded is not first
    assert calls == [1, 2]


def test_flag_based_cache_mutable_data_clears_and_invalidate_touches_file(tmp_path: Path) -> None:
    """Mutable caches should reuse the same object and clear it when stale."""
    flag_file = tmp_path / "nested" / "cache.flag"
    payload: dict[str, str] = {"name": "alice"}
    cache = FlagBasedCache(flag_file, payload)

    first = cache.get()
    assert first is payload
    assert first == {"name": "alice"}

    time.sleep(0.1)  # ensure the filesystem mtime advances before rechecking
    flag_file.parent.mkdir(parents=True, exist_ok=True)
    flag_file.touch()

    refreshed = cache.get()
    assert refreshed is payload
    assert refreshed == {}

    cache.invalidate()
    assert flag_file.exists()
