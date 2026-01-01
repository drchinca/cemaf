"""
Mock cache implementation for testing.
"""

from datetime import datetime
from typing import Any

from cemaf.cache.protocols import CacheEntry, CacheStats
from cemaf.core.types import JSON


class MockCache:
    """
    Mock cache for testing.

    Records all operations for verification in tests.
    """

    def __init__(self, default_return: Any = None) -> None:
        """
        Initialize mock cache.

        Args:
            default_return: Default value to return for get operations.
        """
        self._data: dict[str, CacheEntry] = {}
        self._default_return = default_return
        self._operations: list[tuple[str, str, Any]] = []
        self._hits = 0
        self._misses = 0

    @property
    def operations(self) -> list[tuple[str, str, Any]]:
        """Get recorded operations as (operation, key, value/args) tuples."""
        return list(self._operations)

    @property
    def get_calls(self) -> list[str]:
        """Get all keys that were requested via get()."""
        return [op[1] for op in self._operations if op[0] == "get"]

    @property
    def set_calls(self) -> list[tuple[str, Any]]:
        """Get all (key, value) pairs that were set."""
        return [(op[1], op[2]) for op in self._operations if op[0] == "set"]

    async def get(self, key: str) -> Any | None:
        """Get a value, recording the operation."""
        self._operations.append(("get", key, None))

        entry = self._data.get(key)
        if entry is None or entry.is_expired:
            self._misses += 1
            return self._default_return

        self._hits += 1
        return entry.value

    async def get_entry(self, key: str) -> CacheEntry | None:
        """Get entry with metadata."""
        self._operations.append(("get_entry", key, None))

        entry = self._data.get(key)
        if entry is None or entry.is_expired:
            return None
        return entry

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
        metadata: JSON | None = None,
    ) -> None:
        """Set a value, recording the operation."""
        self._operations.append(("set", key, value))

        from datetime import timedelta

        expires_at = None
        if ttl_seconds is not None:
            expires_at = datetime.now() + timedelta(seconds=ttl_seconds)

        self._data[key] = CacheEntry(
            key=key,
            value=value,
            created_at=datetime.now(),
            expires_at=expires_at,
            metadata=metadata or {},
        )

    async def delete(self, key: str) -> bool:
        """Delete a value, recording the operation."""
        self._operations.append(("delete", key, None))

        if key in self._data:
            del self._data[key]
            return True
        return False

    async def clear(self) -> None:
        """Clear all values, recording the operation."""
        self._operations.append(("clear", "", None))
        self._data.clear()

    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        self._operations.append(("exists", key, None))

        entry = self._data.get(key)
        return entry is not None and not entry.is_expired

    async def stats(self) -> CacheStats:
        """Get mock statistics."""
        return CacheStats(
            hits=self._hits,
            misses=self._misses,
            size=len(self._data),
            evictions=0,
        )

    def reset(self) -> None:
        """Reset mock state."""
        self._data.clear()
        self._operations.clear()
        self._hits = 0
        self._misses = 0

    def preload(self, key: str, value: Any) -> None:
        """
        Preload a value into the cache for testing.

        Does not record as an operation.
        """
        self._data[key] = CacheEntry(
            key=key,
            value=value,
            created_at=datetime.now(),
            expires_at=None,
        )
