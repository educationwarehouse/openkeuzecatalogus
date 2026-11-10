"""Shared session and Redis wiring for the backend."""

import os

from py4web.utils.url_signer import URLSigner
from redis import Redis

from common import settings
from common.fixtures.session import PoppableSession

redis = Redis(host="redis-master", port=6379, password=os.environ["REDIS_PASSWORD"])

session = PoppableSession(
    secret=settings.SESSION_SECRET,
    storage=redis,
    name="shared_session",
    expiration=settings.SESSION_IDLE_SECONDS,
    absolute_expiration=settings.SESSION_ABSOLUTE_SECONDS,
)
grid_action_signer = URLSigner(session=session, lifespan=settings.SIGNED_URL_SECONDS)
grid_action_verified = grid_action_signer.verify()

__all__ = [
    "grid_action_signer",
    "grid_action_verified",
    "redis",
    "session",
]
