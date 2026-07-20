"""Shared session and Redis wiring for the backend."""

from redis import Redis

from common import settings
from common.fixtures import PoppableSession

redis = Redis(host="redis-master", port=6379)

session = PoppableSession(secret=settings.SESSION_SECRET, storage=redis, name="shared_session")

__all__ = [
    "redis",
    "session",
]
