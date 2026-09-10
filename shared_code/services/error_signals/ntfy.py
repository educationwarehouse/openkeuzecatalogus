"""ntfy implementation of the error-signal service."""

import os

import requests

from shared_code.infra.web import PY4WEB_URL

from .contracts import ErrorSignal, ErrorSignalService


class NtfyErrorSignalService(ErrorSignalService):
    """Publish stored-error summaries to an ntfy topic."""

    def __init__(self, error_url: str) -> None:
        """Create an ntfy publisher for the configured topic URL."""
        self.error_url = error_url

    @classmethod
    def from_env(cls) -> NtfyErrorSignalService:
        """Build the ntfy publisher from `NTFY_ERROR_URL`."""
        error_url = os.environ.get("NTFY_ERROR_URL", "").strip()
        if not error_url:
            raise OSError("NTFY_ERROR_URL is required when ERROR_SIGNAL_BACKEND=ntfy")

        return cls(error_url)

    def send_one(self, signal: ErrorSignal) -> bool:
        """Publish one signal through ntfy's JSON API."""
        return self._publish(signal.title, signal.message, signal.click_url)

    def send_batch(self, signals: list[ErrorSignal]) -> bool:
        """Publish one aggregate notification for a batch of error tickets."""
        if not signals:
            return True

        return self._publish(
            title=f"{len(signals)} new error tickets",
            message="\n\n".join(signal.message for signal in signals),
            click_url=self._batch_click_url(signals),
        )

    def _publish(self, title: str, message: str, click_url: str) -> bool:
        """Publish a prepared ntfy notification."""
        base_url, separator, topic = self.error_url.rstrip("/").rpartition("/")
        if not separator or not base_url or not topic:
            raise ValueError("NTFY_ERROR_URL must include an ntfy topic")

        response = requests.post(
            base_url,
            json={
                "topic": topic,
                "title": title,
                "message": message,
                "click": click_url,
                "tags": ["rotating_light"],
                "priority": 4,
            },
            timeout=10,
        )
        response.raise_for_status()
        return True

    @staticmethod
    def _batch_click_url(signals: list[ErrorSignal]) -> str:
        """Return the filtered error-overview URL for the delivered batch."""
        return PY4WEB_URL("admin", "errors", ticket_id=[signal.ticket_id for signal in signals])
