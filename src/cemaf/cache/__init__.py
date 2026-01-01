"""
Cache module.

Provides caching layer for LLM responses and expensive operations
with TTL support and decorator patterns.

Configuration:
    See cemaf.config.protocols.CacheSettings for available settings.
    Environment variables: CEMAF_CACHE_*

Usage:
    # Recommended: Use factories with configuration
    from cemaf.cache import create_cache_from_config
    cache = create_cache_from_config()

    # Direct instantiation
    from cemaf.cache import InMemoryCache
    cache = InMemoryCache(max_size=1000)
"""

from cemaf.cache.decorators import cache_key, cached
from cemaf.cache.factories import create_cache, create_cache_from_config
from cemaf.cache.mock import MockCache
from cemaf.cache.protocols import (
    Cache,
    CacheEntry,
    CacheKey,
    CacheStats,
)
from cemaf.cache.stores import (
    InMemoryCache,
    TTLCache,
)

__all__ = [
    # Protocols
    "Cache",
    "CacheEntry",
    "CacheStats",
    "CacheKey",
    # Stores
    "InMemoryCache",
    "TTLCache",
    # Factories
    "create_cache",
    "create_cache_from_config",
    # Decorators
    "cached",
    "cache_key",
    # Mock
    "MockCache",
]
