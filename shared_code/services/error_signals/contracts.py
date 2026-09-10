"""Error-signal service contract and safe delivery payload."""

import abc
import dataclasses as dc
import json
import os
from pathlib import Path

from diskcache import Deque
from endow import Service

from shared_code.util.lists import batch_deque


@dc.dataclass(frozen=True)
class ErrorSignal:
    """Safe summary of a stored error ticket for an external signal backend."""

    ticket_id: str
    project: str
    application: str
    timestamp: str
    exception_type: str
    exception_message: str
    click_url: str

    @property
    def title(self) -> str:
        """Return the concise notification title."""
        return f"{self.project} {self.application}: {self.exception_type}"

    @property
    def message(self) -> str:
        """Return the notification body without request or user data."""
        return "\n".join(
            (
                f"Ticket: {self.ticket_id}",
                f"Time: {self.timestamp}",
                f"Error: {self.exception_message}",
            )
        )


class ErrorSignalService(Service, abc.ABC):
    """Queue or deliver stored-error signals through the configured backend."""

    def send(self, signal: ErrorSignal, blocking: bool = False) -> bool:
        """Deliver one signal now or add it to the persistent delivery queue."""
        if blocking:
            return self.send_one(signal)

        return self.enqueue(signal)

    @classmethod
    def enqueue(cls, signal: ErrorSignal) -> bool:
        """Add one signal to the persistent delivery queue without building a backend."""
        queue = Deque(directory=cls.queue_path())
        payload = json.dumps(dc.asdict(signal), ensure_ascii=True, sort_keys=True)
        with queue.transact():
            queue.append(payload)
        return True

    @abc.abstractmethod
    def send_one(self, signal: ErrorSignal) -> bool:
        """Deliver one error signal and return whether the backend accepted it."""
        ...

    def send_batch(self, signals: list[ErrorSignal]) -> bool:
        """Deliver a batch using the backend's single-signal primitive."""
        accepted = True
        for signal in signals:
            accepted = self.send_one(signal) and accepted
        return accepted

    def process_queue(self, batch_size: int = 50) -> int:
        """Drain and deliver one persistent queue batch without retrying failures."""
        queue = Deque(directory=self.queue_path())
        payloads = batch_deque(queue, batch_size)
        if not payloads:
            return 0

        signals: list[ErrorSignal] = []
        for payload in payloads:
            try:
                signals.append(ErrorSignal(**json.loads(payload)))
            except Exception as error:
                print(f"[error-signal] invalid queued payload: {type(error).__name__}({error})")

        if signals:
            try:
                self.send_batch(signals)
            except Exception as error:
                print(f"[error-signal] delivery failed: {type(error).__name__}({error})")

        return len(payloads)

    @staticmethod
    def queue_path() -> Path:
        """Return the directory used for pending error-signal payloads."""
        return Path(os.environ["ERROR_SIGNAL_QUEUE_PATH"])

    @classmethod
    def from_env(cls) -> ErrorSignalService:
        """Build the error-signal backend selected by `ERROR_SIGNAL_BACKEND`."""
        backend = os.environ.get("ERROR_SIGNAL_BACKEND", "mock").strip().lower()
        if backend == "mock":
            from .mock import MockErrorSignalService

            return MockErrorSignalService.from_env()
        elif backend == "ntfy":
            from .ntfy import NtfyErrorSignalService

            return NtfyErrorSignalService.from_env()
        else:
            raise ValueError(f"Unsupported ERROR_SIGNAL_BACKEND: {backend!r}")
