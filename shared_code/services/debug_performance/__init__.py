"""Temporary checkpoint timings for investigating slow operations."""

import contextlib
import dataclasses as dc
import os
import time
import typing as t

from endow import GraphBuilder, Service


@dc.dataclass
class PerformanceCheckpoint:
    """One elapsed interval and the nested scopes that ran during it."""

    label: str
    seconds: float
    children: list[DebugPerformanceScope] = dc.field(default_factory=list)


class DebugPerformanceScope:
    """Timing state for a block, reported with its children when the root exits."""

    def __init__(
        self,
        namespace: str,
        enabled: bool = False,
        service: DebugPerformanceService | None = None,
    ) -> None:
        """Prepare timing state for one independently measured block."""
        self.namespace = namespace
        self.enabled = enabled
        self._service = service
        self._parent: DebugPerformanceScope | None = None
        self._started_at: float | None = None
        self._previous_at: float | None = None
        self._checkpoints: list[PerformanceCheckpoint] = []
        self._pending_children: list[DebugPerformanceScope] = []
        self._total_seconds = 0.0
        self._failed = False

    def __enter__(self) -> t.Self:
        """Start the clock and attach this scope to its enclosing measurement."""
        if self.enabled:
            self._checkpoints.clear()
            self._pending_children.clear()
            self._parent = None
            self._failed = False
            if self._service is not None:
                if self._service._stack:
                    self._parent = self._service._stack[-1]
                self._service._stack.append(self)
            self._started_at = self._previous_at = time.perf_counter()
        return self

    def checkpoint(self, label: str) -> None:
        """Record elapsed time since entry or the previous checkpoint."""
        if self._previous_at is None:
            return
        now = time.perf_counter()
        self._record(label, now)
        self._previous_at = now

    def _record(self, label: str, now: float) -> None:
        if self._previous_at is None:
            return
        self._checkpoints.append(
            PerformanceCheckpoint(
                label=label,
                seconds=now - self._previous_at,
                children=self._pending_children,
            )
        )
        self._pending_children = []

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        """Finish timing, report the outermost scope, and restore the scope stack."""
        try:
            if self._started_at is None:
                return
            now = time.perf_counter()
            self._total_seconds = now - self._started_at
            self._failed = exc_type is not None
            self._record("remaining", now)
            if self._parent is not None:
                self._parent._pending_children.append(self)
            else:
                self._report()
        finally:
            if self._started_at is not None and self._service is not None:
                self._service._stack.pop()
            self._started_at = self._previous_at = None
            self._parent = None

    def _lines(self, depth: int = 0) -> list[str]:
        indent = "    " * depth
        status = " [FAILED]" if self._failed else ""
        lines = [f"{indent}{self.namespace}: {self._total_seconds * 1000:.3f} ms total{status}"]
        for checkpoint in sorted(self._checkpoints, key=lambda item: item.seconds, reverse=True):
            percentage = checkpoint.seconds / self._total_seconds * 100 if self._total_seconds else 0.0
            lines.append(f"{indent}  {checkpoint.seconds * 1000:9.3f} ms  {percentage:5.1f}%  {checkpoint.label}")
            for child in sorted(checkpoint.children, key=lambda item: item._total_seconds, reverse=True):
                lines.extend(child._lines(depth=depth + 1))
        return lines

    def _report(self) -> None:
        # Diagnostic output must never replace an application's exception.
        with contextlib.suppress(Exception):
            print("[debug_performance] " + "\n".join(self._lines()) + "\n", flush=True)


class DebugPerformanceService(Service):
    """Create temporary scopes and group nested scopes on a sequential worker."""

    def __init__(self, enabled: bool = False) -> None:
        """Set the explicit enabled state and initialize the shared scope stack."""
        self.enabled = enabled
        self._stack: list[DebugPerformanceScope] = []

    @classmethod
    def from_env(cls, builder: GraphBuilder) -> t.Self:
        """Enable diagnostics in development and test environments."""
        return cls(enabled=os.getenv("STATE_OF_DEVELOPMENT", "").upper() in {"ONT", "TEST"})

    def __call__(self, namespace: str) -> DebugPerformanceScope:
        """Collect checkpoint deltas and print a report when the outer block exits."""
        return DebugPerformanceScope(namespace, enabled=self.enabled, service=self)
