"""Swappable cache service package."""

from .chained import ChainedCacheService
from .contracts import CacheService
from .helpers import build_key, scope_key
from .memory import MemoryCacheService, NullCacheService
from .module import CacheBlock, DependencyRecorder
from .postgres import PostgresCacheService
from .redis import RedisCacheService
from .types import TTL, Dep, DepSet, GidDep, RowDep, Scope, ScopeIdentity, TableDep

__all__ = [
    "TTL",
    "CacheBlock",
    "CacheService",
    "ChainedCacheService",
    "Dep",
    "DepSet",
    "DependencyRecorder",
    "GidDep",
    "MemoryCacheService",
    "NullCacheService",
    "PostgresCacheService",
    "RedisCacheService",
    "RowDep",
    "Scope",
    "ScopeIdentity",
    "TableDep",
    "build_key",
    "scope_key",
]
