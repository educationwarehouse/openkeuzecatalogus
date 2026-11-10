"""Shared py4web fixtures used by common application routes."""

from .common import CommonHelpers, common
from .content_editable import ContentEditableV2
from .error_ticket_helper import (
    ErrorTicketHelper,
    error_ticket_helper,
)
from .flag_based_cache import FlagBasedCache
from .requires_fixture import RequiresFixture
from .route_stats import RouteStats, RouteStatsFixture, request_signature, route_stats
from .session import PoppableSession
from .settings import SettingsFixture
from .static_hash import StaticHash, static_hash

__all__ = [
    "CommonHelpers",
    "ContentEditableV2",
    "ErrorTicketHelper",
    "FlagBasedCache",
    "PoppableSession",
    "RequiresFixture",
    "RouteStats",
    "RouteStatsFixture",
    "SettingsFixture",
    "StaticHash",
    "common",
    "error_ticket_helper",
    "request_signature",
    "route_stats",
    "static_hash",
]
