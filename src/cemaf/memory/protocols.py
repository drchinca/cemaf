"""
Memory protocols - Abstract interfaces for memory storage.

Supports:
- Scoped storage (tenant, project, session, etc.)
- TTL and expiration
- Confidence scoring
- Redaction hooks for PII removal
- Custom serialization

## Protocol-First Design

This module provides structural typing via @runtime_checkable protocols.
Any class that implements the required methods is automatically compatible.

Extension Point:
    Custom memory store implementations should implement these protocols
    rather than inheriting from ABC classes. This allows maximum flexibility
    and follows CEMAF's dependency injection principles.

Example:
    >>> from cemaf.core.enums import MemoryScope
    >>> from cemaf.memory.protocols import MemoryItem, MemoryStore
    >>>
    >>> class MyCustomMemoryStore:
    ...     async def get(self, scope: MemoryScope, key: str) -> MemoryItem | None:
    ...         # Your implementation
    ...         ...
    ...
    ...     async def set(self, item: MemoryItem) -> None:
    ...         # Your implementation
    ...         ...
    ...
    ...     async def delete(self, scope: MemoryScope, key: str) -> bool:
    ...         # Your implementation
    ...         ...
    ...
    ...     async def list_by_scope(self, scope: MemoryScope) -> tuple[MemoryItem, ...]:
    ...         # Your implementation
    ...         ...
    >>>
    >>> # No inheritance needed - structural compatibility!
    >>> assert isinstance(MyCustomMemoryStore(), MemoryStore)
"""

from typing import Protocol, runtime_checkable

from cemaf.core.enums import MemoryScope

# Re-export data classes and types from base (these are not changed)
from cemaf.memory.base import MemoryItem, RedactionHook, SerializationHook

__all__ = [
    "MemoryStore",
    "MemoryItem",
    "RedactionHook",
    "SerializationHook",
]


@runtime_checkable
class MemoryStore(Protocol):
    """
    Protocol for memory store implementations.

    A MemoryStore is a key-value storage system that:
    - Organizes data by scopes (tenant, project, session, etc.)
    - Supports TTL and automatic expiration
    - Tracks confidence scores for items
    - Provides hooks for redaction and serialization
    - Handles async I/O for all operations

    This is a protocol, not an ABC. Any class with these methods is compatible.

    Extension Point:
        Implement this protocol for custom backends:
        - InMemory (testing, session-scoped)
        - Redis (distributed cache)
        - PostgreSQL (persistent)
        - DynamoDB (cloud)
        - MongoDB (document store)
        - SQLite (local persistent)

    Example:
        >>> import json
        >>> from datetime import datetime
        >>> from cemaf.core.types import Confidence
        >>>
        >>> def _decode_item(data: str) -> MemoryItem:
        ...     raw = json.loads(data)
        ...     return MemoryItem(
        ...         scope=MemoryScope(raw["scope"]),
        ...         key=raw["key"],
        ...         value=raw["value"],
        ...         confidence=Confidence(raw["confidence"]),
        ...         created_at=datetime.fromisoformat(raw["created_at"]),
        ...         updated_at=datetime.fromisoformat(raw["updated_at"]),
        ...         expires_at=(
        ...             datetime.fromisoformat(raw["expires_at"])
        ...             if raw.get("expires_at")
        ...             else None
        ...         ),
        ...         scope_path=raw.get("scope_path"),
        ...     )
        >>>
        >>> def _encode_item(item: MemoryItem) -> str:
        ...     return json.dumps(
        ...         {
        ...             "scope": item.scope.value,
        ...             "key": item.key,
        ...             "value": item.value,
        ...             "confidence": float(item.confidence),
        ...             "created_at": item.created_at.isoformat(),
        ...             "updated_at": item.updated_at.isoformat(),
        ...             "expires_at": item.expires_at.isoformat() if item.expires_at else None,
        ...             "scope_path": item.scope_path,
        ...         }
        ...     )
        >>>
        >>> class RedisMemoryStore:
        ...     def __init__(self, redis_client):
        ...         self._redis = redis_client
        ...
        ...     async def get(self, scope: MemoryScope, key: str) -> MemoryItem | None:
        ...         full_key = f"{scope.value}:{key}"
        ...         data = await self._redis.get(full_key)
        ...         if not data:
        ...             return None
        ...         if isinstance(data, bytes):
        ...             data = data.decode()
        ...         return _decode_item(data)
        ...
        ...     async def set(self, item: MemoryItem) -> None:
        ...         full_key = item.full_key
        ...         data = _encode_item(item)
        ...         ttl = item.remaining_ttl
        ...         if ttl is not None:
        ...             await self._redis.set(full_key, data, ex=max(1, int(ttl.total_seconds())))
        ...         else:
        ...             await self._redis.set(full_key, data)
        ...
        ...     async def delete(self, scope: MemoryScope, key: str) -> bool:
        ...         full_key = f"{scope.value}:{key}"
        ...         deleted = await self._redis.delete(full_key)
        ...         return deleted > 0
        ...
        ...     async def list_by_scope(self, scope: MemoryScope) -> tuple[MemoryItem, ...]:
        ...         pattern = f"{scope.value}:*"
        ...         keys = await self._redis.keys(pattern)
        ...         items = []
        ...         for key in keys:
        ...             data = await self._redis.get(key)
        ...             if data:
        ...                 if isinstance(data, bytes):
        ...                     data = data.decode()
        ...                 items.append(_decode_item(data))
        ...         return tuple(items)
        >>>
        >>> # Automatically compatible - no inheritance!
        >>> store = RedisMemoryStore(redis_client)
        >>> assert isinstance(store, MemoryStore)

    Best Practices:
        1. **Async I/O**: All methods are async for consistent interface
        2. **Immutability**: MemoryItems are frozen dataclasses
        3. **Expiration**: Check and cleanup expired items on retrieval
        4. **Redaction**: Apply redaction hooks before returning items
        5. **Scoping**: Use MemoryScope enum for proper isolation
        6. **Error Handling**: Return None for missing items, never raise

    Memory Scopes:
        CEMAF defines domain-neutral scopes for different lifetimes:
        - GLOBAL: framework-wide/shared memory
        - TENANT: tenant/org/workspace isolation boundary
        - PROJECT: project-specific knowledge
        - USER: end-user scoped preferences and facts
        - SESSION: short-lived run/session memory
        - STRATEGY: cross-run learned patterns

    See Also:
        - cemaf.memory.base.MemoryStore - ABC base class (recommended for most implementations)
        - This Protocol - For advanced structural typing without inheritance
        - cemaf.memory.base.InMemoryStore (reference implementation)
        - cemaf.core.enums.MemoryScope (scope definitions)

    Usage Guide:
        - Use ABC when you want helper methods and clear inheritance
        - Use Protocol when you need duck typing or wrapping existing objects
        - Function signatures should use Protocol for maximum flexibility
    """

    async def get(self, scope: MemoryScope, key: str) -> MemoryItem | None:
        """
        Retrieve a memory item by scope and key.

        Args:
            scope: Memory scope (tenant, project, session, etc.)
            key: Unique key within the scope

        Returns:
            MemoryItem if found and not expired, None otherwise

        Example:
            >>> item = await store.get(MemoryScope.TENANT, "company_name")
            >>> if item:
            ...     print(f"Company: {item.value}")
        """
        ...

    async def set(self, item: MemoryItem) -> None:
        """
        Store a memory item.

        If an item with the same scope+key exists, it will be replaced.

        Args:
            item: MemoryItem to store (contains scope, key, value, TTL, etc.)

        Example:
            >>> from datetime import timedelta
            >>> item = MemoryItem(
            ...     scope=MemoryScope.TENANT,
            ...     key="company_name",
            ...     value={"name": "Acme Corp"},
            ...     confidence=Confidence(0.9),
            ...     ttl=timedelta(days=30)
            ... )
            >>> await store.set(item)
        """
        ...

    async def delete(self, scope: MemoryScope, key: str) -> bool:
        """
        Delete a memory item.

        Args:
            scope: Memory scope
            key: Key to delete

        Returns:
            True if item existed and was deleted, False if not found

        Example:
            >>> deleted = await store.delete(MemoryScope.SESSION, "temp_data")
            >>> if deleted:
            ...     print("Item removed")
        """
        ...

    async def list_by_scope(self, scope: MemoryScope) -> tuple[MemoryItem, ...]:
        """
        List all non-expired items in a scope.

        Args:
            scope: Memory scope to list

        Returns:
            Tuple of MemoryItems in the scope (excludes expired items)

        Example:
            >>> items = await store.list_by_scope(MemoryScope.TENANT)
            >>> for item in items:
            ...     print(f"{item.key}: {item.value}")
        """
        ...

    async def cleanup_expired(self) -> int:
        """
        Remove all expired items from the store.

        This is typically called periodically for maintenance.
        Some stores may handle expiration automatically (e.g., Redis TTL).

        Returns:
            Number of items removed

        Example:
            >>> # Run cleanup task periodically
            >>> removed = await store.cleanup_expired()
            >>> print(f"Cleaned up {removed} expired items")
        """
        ...
