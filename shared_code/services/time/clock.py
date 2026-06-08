"""Time helpers."""

import datetime as dt


def utcnow() -> dt.datetime:
    """Replacement for deprecated `datetime.utcnow()`."""
    return dt.datetime.now(dt.UTC)


def ensure_utc(timestamp: dt.datetime) -> dt.datetime:
    """Return a timezone-aware UTC datetime for naive or aware inputs."""
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=dt.UTC)
    return timestamp.astimezone(dt.UTC)


def normalize_timestamp(timestamp: str | dt.datetime | int) -> str:
    """Normalize supported timestamp inputs to an ISO string value."""
    if isinstance(timestamp, int | float):
        timestamp = dt.datetime.fromtimestamp(timestamp)
    if isinstance(timestamp, dt.datetime):
        return timestamp.isoformat()
    else:
        return str(timestamp)
