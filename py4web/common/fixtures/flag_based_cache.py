"""Shared file-backed cache helper for cross-process invalidation."""

import time
import typing as t
from pathlib import Path


class FlagBasedCache[T]:
    """Cache that invalidates across multiple process instances using file mtime.

    Works by checking a shared flag file's modification time. When any instance
    calls invalidate(), all other instances detect the change and refresh their cache.

    Supports two modes:
    - Callable: provide a loader function that rebuilds cache data when stale
    - Mutable data: provide a dict/list that gets cleared when stale
    - No data: just track staleness (e.g., for restart flag)

    Usage:
        # With loader function
        cache = FlagBasedCache(Path("/shared/cache.flag"), lambda: load_data())
        data = cache.get()  # auto-reloads if stale

        # With mutable dict
        cache = FlagBasedCache(Path("/shared/cache.flag"), {})
        data = cache.get()  # dict cleared if stale, returns same dict

        # Invalidate from any instance
        cache.invalidate()  # touches flag file, all instances see it
    """

    def __init__(self, flag_file: Path, data: t.Callable[[], T] | T | None = None) -> None:
        """Initialize cache with flag file and data source.

        Args:
            flag_file: Shared file path to track invalidation (e.g., /shared_cache/xyz.flag)
            data: Either a callable that loads data, or initial mutable data, or None

        """
        self.flag_file = flag_file
        self.data = data
        self._last_mtime = time.time()
        self._cache: T | None = None

    @classmethod
    def last_touched(cls, file_path: Path) -> float:
        """Get the last modification time of a file."""
        return file_path.stat().st_mtime

    def is_stale(self) -> bool:
        """Check if cache is stale based on flag file mtime.

        Returns True if flag file was touched since we last loaded the cache.
        """
        if not self.flag_file.exists():
            return False

        current_mtime = self.last_touched(self.flag_file)

        return current_mtime > self._last_mtime

    def get(self) -> T:
        """Get cached data, reloading or clearing if stale.

        - Callable data: re-runs loader function when stale
        - Dict data: clears dict when stale, returns same reference
        - Other data: returns as-is
        """
        # Return early if cache is fresh
        if self._cache is not None and not self.is_stale():
            return self._cache

        # Refresh callable data
        if callable(self.data):
            self._cache = self.data()  # type: ignore
            self._last_mtime = time.time()
            return self._cache  # type: ignore

        # Handle pre-initialized data
        if self.data is not None:
            if self._cache is None:
                self._cache = self.data
            elif isinstance(self._cache, dict):
                self._cache.clear()
            self._last_mtime = time.time()

        return self._cache  # type: ignore

    def invalidate(self) -> None:
        """Touch flag file to invalidate cache across all instances.

        Creates parent directory if needed. All instances will detect
        the change on their next is_stale() or get() call.
        """
        self.flag_file.parent.mkdir(parents=True, exist_ok=True)
        self.flag_file.touch()
