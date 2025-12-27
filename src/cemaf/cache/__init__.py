"""
Cache module.

Provides caching layer for LLM responses and expensive operations
with TTL support and decorator patterns.
"""

from cemaf.cache.protocols import (
    Cache,
    CacheEntry,
    CacheStats,
    CacheKey,
)
from cemaf.cache.stores import (
    InMemoryCache,
    TTLCache,
)
from cemaf.cache.decorators import cached, cache_key
from cemaf.cache.mock import MockCache

__all__ = [
    # Protocols
    "Cache",
    "CacheEntry",
    "CacheStats",
    "CacheKey",
    # Stores
    "InMemoryCache",
    "TTLCache",
    # Decorators
    "cached",
    "cache_key",
    # Mock
    "MockCache",
]

