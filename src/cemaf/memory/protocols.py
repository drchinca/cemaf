"""
Memory protocols - Abstract interfaces for memory storage.

Supports:
- Scoped storage (brand, project, conversation, turn, etc.)
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
    >>> from cemaf.memory.protocols import MemoryStore
    >>> from cemaf.core.enums import MemoryScope
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
    - Organizes data by scopes (brand, project, conversation, etc.)
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
        >>> class RedisMemoryStore:
        ...     def __init__(self, redis_client):
        ...         self._redis = redis_client
        ...
        ...     async def get(self, scope: MemoryScope, key: str) -> MemoryItem | None:
        ...         full_key = f"{scope.value}:{key}"
        ...         data = await self._redis.get(full_key)
        ...         if not data:
        ...             return None
        ...         return MemoryItem.from_json(data)
        ...
        ...     async def set(self, item: MemoryItem) -> None:
        ...         full_key = item.full_key
        ...         data = item.serialize()
        ...         if item.ttl:
        ...             await self._redis.setex(full_key, item.ttl.total_seconds(), data)
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
        ...                 items.append(MemoryItem.from_json(data))
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
        CEMAF defines several built-in memory scopes for different contexts:
        - BRAND: Brand-level knowledge (shared across all projects)
        - PROJECT: Project-specific knowledge
        - AUDIENCE_SEGMENT: Segment-specific knowledge
        - PLATFORM: Platform-specific knowledge
        - PERSONAE: Persona-specific knowledge
        - CONVERSATION: Conversation-scoped (cleared after each conversation)
        - TURN: Turn-scoped (cleared after each turn)

    See Also:
        - cemaf.memory.base.MemoryStore (deprecated ABC, use this protocol instead)
        - cemaf.memory.base.InMemoryStore (reference implementation)
        - cemaf.core.enums.MemoryScope (scope definitions)
    """

    async def get(self, scope: MemoryScope, key: str) -> MemoryItem | None:
        """
        Retrieve a memory item by scope and key.

        Args:
            scope: Memory scope (brand, project, conversation, etc.)
            key: Unique key within the scope

        Returns:
            MemoryItem if found and not expired, None otherwise

        Example:
            >>> item = await store.get(MemoryScope.BRAND, "company_name")
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
            ...     scope=MemoryScope.BRAND,
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
            >>> deleted = await store.delete(MemoryScope.CONVERSATION, "temp_data")
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
            >>> items = await store.list_by_scope(MemoryScope.BRAND)
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
