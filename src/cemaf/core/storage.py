"""
Generic in-memory storage for consistent patterns across modules.

Eliminates the need for separate InMemory* classes in each module.
All modules can use or extend InMemoryStorage[K, V].

Example:
    from cemaf.core.storage import InMemoryStorage

    # Simple key-value store
    store: InMemoryStorage[str, User] = InMemoryStorage()
    await store.set("user_1", user)
    user = await store.get("user_1")
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from cemaf.core.utils import utc_now


@dataclass
class StorageEntry[V]:
    """Entry in storage with optional TTL."""

    value: V
    created_at: datetime = field(default_factory=utc_now)
    expires_at: datetime | None = None
    access_count: int = 0

    @property
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        if self.expires_at is None:
            return False
        return utc_now() > self.expires_at


class InMemoryStorage[K, V]:
    """
    Generic in-memory key-value storage.

    Features:
    - Async interface (consistent with other stores)
    - Optional TTL per entry
    - Max size with LRU eviction
    - Hit/miss statistics

    Replaces: InMemoryStore, InMemoryCache, InMemoryCheckpointer,
              InMemoryConfigSource, InMemoryVectorStore, etc.
    """

    def __init__(
        self,
        max_size: int | None = None,
        default_ttl_seconds: int | None = None,
    ) -> None:
        """
        Initialize storage.

        Args:
            max_size: Maximum entries (None = unlimited)
            default_ttl_seconds: Default TTL for entries (None = no expiry)
        """
        self._data: dict[K, StorageEntry[V]] = {}
        self._max_size = max_size
        self._default_ttl = default_ttl_seconds
        self._hits = 0
        self._misses = 0

    async def get(self, key: K) -> V | None:
        """Get a value by key."""
        entry = self._data.get(key)

        if entry is None:
            self._misses += 1
            return None

        if entry.is_expired:
            del self._data[key]
            self._misses += 1
            return None

        self._hits += 1
        entry.access_count += 1
        return entry.value

    async def set(
        self,
        key: K,
        value: V,
        ttl_seconds: int | None = None,
    ) -> None:
        """Set a value with optional TTL."""
        # Evict if at capacity
        if self._max_size and len(self._data) >= self._max_size and key not in self._data:
            await self._evict_lru()

        # Calculate expiry
        expires_at = None
        effective_ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        if effective_ttl is not None:
            expires_at = utc_now() + timedelta(seconds=effective_ttl)

        self._data[key] = StorageEntry(
            value=value,
            expires_at=expires_at,
        )

    async def delete(self, key: K) -> bool:
        """Delete a key. Returns True if existed."""
        if key in self._data:
            del self._data[key]
            return True
        return False

    async def exists(self, key: K) -> bool:
        """Check if key exists and is not expired."""
        entry = self._data.get(key)
        if entry is None:
            return False
        if entry.is_expired:
            del self._data[key]
            return False
        return True

    async def clear(self) -> None:
        """Clear all entries."""
        self._data.clear()

    async def keys(self) -> list[K]:
        """Get all non-expired keys."""
        await self._cleanup_expired()
        return list(self._data.keys())

    async def values(self) -> list[V]:
        """Get all non-expired values."""
        await self._cleanup_expired()
        return [e.value for e in self._data.values()]

    async def items(self) -> list[tuple[K, V]]:
        """Get all non-expired key-value pairs."""
        await self._cleanup_expired()
        return [(k, e.value) for k, e in self._data.items()]

    async def size(self) -> int:
        """Get number of non-expired entries."""
        await self._cleanup_expired()
        return len(self._data)

    @property
    def stats(self) -> dict[str, int]:
        """Get hit/miss statistics."""
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "size": len(self._data),
            "hit_rate_pct": int((self._hits / total * 100) if total > 0 else 0),
        }

    async def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        if not self._data:
            return

        # Find entry with lowest access count (simple LRU approximation)
        lru_key = min(self._data.keys(), key=lambda k: self._data[k].access_count)
        del self._data[lru_key]

    async def _cleanup_expired(self) -> None:
        """Remove all expired entries."""
        expired = [k for k, v in self._data.items() if v.is_expired]
        for key in expired:
            del self._data[key]


class AsyncDict(InMemoryStorage[str, Any]):
    """
    Simple async dict wrapper.

    For cases where you just need basic key-value with async interface.
    """

    def __init__(self) -> None:
        super().__init__()

    def __setitem__(self, key: str, value: Any) -> None:
        """Sync set for convenience."""
        self._data[key] = StorageEntry(value=value)

    def __getitem__(self, key: str) -> Any:
        """Sync get for convenience."""
        entry = self._data.get(key)
        if entry is None or entry.is_expired:
            raise KeyError(key)
        return entry.value

    def __contains__(self, key: str) -> bool:
        """Sync contains check."""
        entry = self._data.get(key)
        return entry is not None and not entry.is_expired
