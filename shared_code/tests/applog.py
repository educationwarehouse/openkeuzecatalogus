"""Test helpers for inspecting applog events."""

from shared_code.services.applog.contracts import ApplogEvent, Applogger


class RecordingApplogger(Applogger):
    """Capture applog events without persisting them."""

    def __init__(self) -> None:
        self.fired_events: list[ApplogEvent] = []

    def fire(self, event: ApplogEvent) -> bool:
        self.fired_events.append(event)
        return True

    @classmethod
    def from_env(cls) -> Applogger:
        """Construct a recorder instead of selecting a production logger."""
        return cls()
