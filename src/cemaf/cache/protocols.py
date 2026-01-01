"""
Cache protocols and base types.

Defines the contracts for cache stores and entries.
"""

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from cemaf.core.types import JSON
from cemaf.core.utils import utc_now


class CacheEntry(BaseModel):
    """A cached value with metadata."""

    model_config = {"frozen": True}

    key: str
    value: Any
    created_at: datetime
    expires_at: datetime | None = None
    hit_count: int = 0
    metadata: JSON = Field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Check if entry is expired."""
        if self.expires_at is None:
            return False
        return utc_now() >= self.expires_at

    def with_hit(self) -> CacheEntry:
        """Return a new entry with incremented hit count."""
        return CacheEntry(
            key=self.key,
            value=self.value,
            created_at=self.created_at,
            expires_at=self.expires_at,
            hit_count=self.hit_count + 1,
            metadata=self.metadata,
        )


class CacheStats(BaseModel):
    """Statistics for a cache."""

    model_config = {"frozen": True}

    hits: int = 0
    misses: int = 0
    size: int = 0
    evictions: int = 0

    @property
    def hit_rate(self) -> float:
        """Calculate hit rate as percentage."""
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return (self.hits / total) * 100


CacheKey = str


@runtime_checkable
class Cache(Protocol):
    """
    Protocol for cache stores.

    Provides async get/set/delete operations with optional TTL.
    """

    async def get(self, key: str) -> Any | None:
        """
        Get a value from cache.

        Args:
            key: Cache key.

        Returns:
            Cached value or None if not found/expired.
        """
        ...

    async def get_entry(self, key: str) -> CacheEntry | None:
        """
        Get a cache entry with metadata.

        Args:
            key: Cache key.

        Returns:
            CacheEntry or None if not found/expired.
        """
        ...

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
        metadata: JSON | None = None,
    ) -> None:
        """
        Set a value in cache.

        Args:
            key: Cache key.
            value: Value to cache.
            ttl_seconds: Time-to-live in seconds (None = no expiry).
            metadata: Optional metadata to store with entry.
        """
        ...

    async def delete(self, key: str) -> bool:
        """
        Delete a value from cache.

        Args:
            key: Cache key.

        Returns:
            True if key existed and was deleted.
        """
        ...

    async def clear(self) -> None:
        """Clear all cached values."""
        ...

    async def exists(self, key: str) -> bool:
        """
        Check if key exists in cache (not expired).

        Args:
            key: Cache key.

        Returns:
            True if key exists and is not expired.
        """
        ...

    async def stats(self) -> CacheStats:
        """
        Get cache statistics.

        Returns:
            CacheStats with hits, misses, size, etc.
        """
        ...
