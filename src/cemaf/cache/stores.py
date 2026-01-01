"""
Cache store implementations.

Simple in-memory cache with optional TTL.
"""

from datetime import timedelta
from typing import Any

from cemaf.cache.protocols import CacheEntry, CacheStats
from cemaf.core.types import JSON
from cemaf.core.utils import utc_now


class InMemoryCache:
    """Simple in-memory cache with optional TTL."""

    def __init__(self, max_size: int | None = None) -> None:
        self._entries: dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    async def get(self, key: str) -> Any | None:
        entry = await self.get_entry(key)
        return entry.value if entry else None

    async def get_entry(self, key: str) -> CacheEntry | None:
        entry = self._entries.get(key)
        if entry is None:
            self._misses += 1
            return None
        if entry.is_expired:
            del self._entries[key]
            self._misses += 1
            return None
        self._hits += 1
        updated = entry.with_hit()
        self._entries[key] = updated
        return updated

    async def set(
        self, key: str, value: Any, ttl_seconds: int | None = None, metadata: JSON | None = None
    ) -> None:
        if self._max_size and len(self._entries) >= self._max_size and key not in self._entries:
            await self._evict_oldest()

        now = utc_now()
        expires_at = now + timedelta(seconds=ttl_seconds) if ttl_seconds is not None else None
        self._entries[key] = CacheEntry(
            key=key,
            value=value,
            created_at=now,
            expires_at=expires_at,
            metadata=metadata or {},
        )

    async def delete(self, key: str) -> bool:
        if key in self._entries:
            del self._entries[key]
            return True
        return False

    async def clear(self) -> None:
        self._entries.clear()

    async def exists(self, key: str) -> bool:
        entry = self._entries.get(key)
        return not (entry is None or entry.is_expired)

    async def stats(self) -> CacheStats:
        await self._cleanup_expired()
        return CacheStats(
            hits=self._hits, misses=self._misses, size=len(self._entries), evictions=self._evictions
        )

    async def _evict_oldest(self) -> None:
        if self._entries:
            oldest = min(self._entries.keys(), key=lambda k: self._entries[k].created_at)
            del self._entries[oldest]
            self._evictions += 1

    async def _cleanup_expired(self) -> None:
        expired = [k for k, v in self._entries.items() if v.is_expired]
        for key in expired:
            del self._entries[key]


class TTLCache(InMemoryCache):
    """Cache with default TTL for all entries."""

    def __init__(self, default_ttl_seconds: int = 3600, max_size: int | None = None) -> None:
        super().__init__(max_size=max_size)
        self._default_ttl = default_ttl_seconds

    async def set(
        self, key: str, value: Any, ttl_seconds: int | None = None, metadata: JSON | None = None
    ) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        await super().set(key, value, ttl, metadata)
