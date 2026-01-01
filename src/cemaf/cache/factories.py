"""
Factory functions for cache components.

Provides convenient ways to create cache stores with sensible defaults
while maintaining dependency injection principles.

Extension Point:
    This module is designed for extension. The create_cache_from_config()
    function includes a clear "EXTEND HERE" section where you can add
    your own cache backend implementations (Redis, Memcached, etc.).
"""

from cemaf.cache.protocols import Cache
from cemaf.cache.stores import InMemoryCache, TTLCache
from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings


def create_cache(
    backend: str = "memory",
    max_size: int = 10000,
    ttl_seconds: float | None = None,
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
    if backend == "memory":
        return InMemoryCache(max_size=max_size)
    elif backend == "ttl":
        if ttl_seconds is None:
            ttl_seconds = 3600.0  # Default 1 hour
        return TTLCache(max_size=max_size, ttl_seconds=ttl_seconds)
    else:
        raise ValueError(f"Unsupported cache backend: {backend}")


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
    cfg = settings or load_settings_from_env_sync()  # noqa: F841

    backend = cfg.cache.backend
    max_size = cfg.cache.max_size
    ttl_seconds = float(cfg.cache.default_ttl_seconds)

    # BUILT-IN IMPLEMENTATIONS
    if backend in ("memory", "ttl"):
        return create_cache(
            backend=backend,
            max_size=max_size,
            ttl_seconds=ttl_seconds if backend == "ttl" else None,
        )

    # ============================================================================
    # EXTEND HERE: Bring Your Own Cache Backend
    # ============================================================================
    # This is the extension point for custom cache backends.
    #
    # To add your own implementation:
    # 1. Implement the Cache protocol (see cemaf.cache.protocols)
    # 2. Add your backend case below
    # 3. Read configuration from environment variables or settings
    #
    # Example:
    #   elif backend == "redis":
    #       from your_package import RedisCache
    #       redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    #       return RedisCache(url=redis_url, max_size=max_size)
    #
    #   elif backend == "memcached":
    #       from your_package import MemcachedCache
    #       servers = os.getenv("MEMCACHED_SERVERS", "localhost:11211").split(",")
    #       return MemcachedCache(servers=servers)
    # ============================================================================

    raise ValueError(
        f"Unsupported cache backend: {backend}. "
        f"Supported: memory, ttl. "
        f"To add your own, extend create_cache_from_config() "
        f"in cemaf/cache/factories.py"
    )
