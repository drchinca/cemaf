"""
Factory functions for cache components.

Provides convenient ways to create cache stores with sensible defaults
while maintaining dependency injection principles.

Extension Point:
    Register custom cache backends with cache_registry.register(...).
"""

import os
from typing import Any

from cemaf.cache.protocols import Cache
from cemaf.cache.stores import InMemoryCache, TTLCache
from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.core.provider_registry import ProviderRegistry

cache_registry: ProviderRegistry[Cache] = ProviderRegistry(name="cache")


def _create_memory_cache(**kwargs: Any) -> Cache:
    return InMemoryCache(max_size=int(kwargs.get("max_size", 10000)))


def _create_ttl_cache(**kwargs: Any) -> Cache:
    ttl_seconds = kwargs.get("ttl_seconds")
    if ttl_seconds is None:
        ttl_seconds = kwargs.get("default_ttl_seconds", 3600.0)
    return TTLCache(
        max_size=int(kwargs.get("max_size", 10000)),
        default_ttl_seconds=int(float(ttl_seconds)),
    )


cache_registry.register(backend="memory", factory=_create_memory_cache)
cache_registry.register(backend="ttl", factory=_create_ttl_cache)


def create_cache(
    backend: str = "memory",
    max_size: int = 10000,
    ttl_seconds: float | None = None,
    **backend_options: Any,
) -> Cache:
    """
    Factory for Cache with sensible defaults.

    Args:
        backend: Cache backend type (memory, ttl)
        max_size: Maximum cache entries
        ttl_seconds: Time-to-live in seconds (only for TTL backend)

    Returns:
        Configured Cache instance

    Example:
        # In-memory cache (no TTL)
        cache = create_cache()

        # TTL cache with expiration
        cache = create_cache(backend="ttl", ttl_seconds=3600.0)
    """
    return cache_registry.create(
        backend=backend,
        max_size=max_size,
        ttl_seconds=ttl_seconds,
        **backend_options,
    )


def create_cache_from_config(settings: Settings | None = None) -> Cache:
    """
    Create Cache from Settings configuration.

    Reads from Settings (which loads from environment variables):
    - CEMAF_CACHE_BACKEND: Backend type (default: "memory")
    - CEMAF_CACHE_MAX_SIZE: Max cache entries (default: 1000)
    - CEMAF_CACHE_DEFAULT_TTL_SECONDS: TTL for cache entries (default: 3600)

    Args:
        settings: Settings instance (loads from env if None)

    Returns:
        Configured Cache instance

    Example:
        # From environment (via Settings)
        cache = create_cache_from_config()

        # With explicit settings
        settings = Settings(...)
        cache = create_cache_from_config(settings=settings)
    """
    cfg = settings or load_settings_from_env_sync()

    backend = str(os.getenv("CEMAF_CACHE_BACKEND", cfg.cache.backend))
    max_size = int(os.getenv("CEMAF_CACHE_MAX_SIZE", str(cfg.cache.max_size)))
    ttl_seconds = float(os.getenv("CEMAF_CACHE_DEFAULT_TTL_SECONDS", str(cfg.cache.default_ttl_seconds)))

    return create_cache(
        backend=backend,
        max_size=max_size,
        ttl_seconds=ttl_seconds,
    )
