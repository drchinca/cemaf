"""
Cache decorators for easy caching of function results.
"""

import functools
import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any, ParamSpec, TypeVar

from cemaf.cache.protocols import Cache

P = ParamSpec("P")
R = TypeVar("R")


def cache_key(*args: Any, **kwargs: Any) -> str:
    """
    Generate a cache key from function arguments.

    Creates a deterministic hash from args and kwargs.

    Args:
        *args: Positional arguments.
        **kwargs: Keyword arguments.

    Returns:
        Hash string suitable for cache key.
    """
    # Create a hashable representation
    key_parts = []

    for arg in args:
        key_parts.append(_serialize_arg(arg))

    for k, v in sorted(kwargs.items()):
        key_parts.append(f"{k}={_serialize_arg(v)}")

    key_str = "|".join(key_parts)
    return hashlib.sha256(key_str.encode()).hexdigest()[:32]


def _serialize_arg(arg: Any) -> str:
    """Serialize an argument to a string for hashing."""
    if isinstance(arg, (str, int, float, bool, type(None))):
        return json.dumps(arg)
    if isinstance(arg, (list, tuple)):
        return json.dumps([_serialize_arg(x) for x in arg])
    if isinstance(arg, dict):
        return json.dumps({k: _serialize_arg(v) for k, v in sorted(arg.items())})
    # Fall back to repr for other types
    return repr(arg)


def cached(
    cache: Cache,
    ttl_seconds: int | None = None,
    key_prefix: str = "",
    key_fn: Callable[..., str] | None = None,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """
    Decorator to cache async function results.

    Args:
        cache: Cache instance to use.
        ttl_seconds: TTL for cached values (None = no expiry).
        key_prefix: Prefix for cache keys.
        key_fn: Custom function to generate cache key from args.

    Returns:
        Decorated function.

    Example:
        ```python
        cache = InMemoryCache()

        @cached(cache, ttl_seconds=3600)
        async def expensive_call(prompt: str) -> str:
            return await llm.complete(prompt)
        ```
    """

    def decorator(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            # Generate cache key
            key = key_fn(*args, **kwargs) if key_fn is not None else cache_key(*args, **kwargs)

            key = f"{key_prefix}:{key}" if key_prefix else f"{fn.__name__}:{key}"

            # Check cache
            cached_value = await cache.get(key)
            if cached_value is not None:
                return cached_value  # type: ignore[return-value]

            # Call function
            result = await fn(*args, **kwargs)

            # Store in cache
            await cache.set(key, result, ttl_seconds)

            return result

        # Add cache bypass method
        wrapper.uncached = fn  # type: ignore[attr-defined]
        wrapper.cache = cache  # type: ignore[attr-defined]

        return wrapper

    return decorator


def cached_property(
    cache: Cache,
    ttl_seconds: int | None = None,
    key: str | None = None,
) -> Callable[[Callable[[Any], Awaitable[R]]], Callable[[Any], Awaitable[R]]]:
    """
    Decorator to cache async property results.

    Similar to @cached but for instance methods that act as properties.

    Args:
        cache: Cache instance to use.
        ttl_seconds: TTL for cached values.
        key: Static cache key (if None, uses method name + instance id).

    Returns:
        Decorated method.
    """

    def decorator(fn: Callable[[Any], Awaitable[R]]) -> Callable[[Any], Awaitable[R]]:
        @functools.wraps(fn)
        async def wrapper(self: Any) -> R:
            # Generate cache key
            cache_k = key if key is not None else f"{type(self).__name__}:{id(self)}:{fn.__name__}"

            # Check cache
            cached_value = await cache.get(cache_k)
            if cached_value is not None:
                return cached_value  # type: ignore[return-value]

            # Call method
            result = await fn(self)

            # Store in cache
            await cache.set(cache_k, result, ttl_seconds)

            return result

        return wrapper

    return decorator
