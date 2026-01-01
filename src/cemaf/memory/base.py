"""
Memory base classes and in-memory implementation.

Memory items have:
- Scope (brand, project, etc.)
- Key (unique within scope)
- Value (JSON-serializable)
- Confidence score
- TTL (time-to-live)
- Redaction/serialization hooks
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from cemaf.core.enums import MemoryScope
from cemaf.core.types import JSON, Confidence
from cemaf.core.utils import utc_now

# Type aliases for hooks
RedactionHook = Callable[["MemoryItem"], "MemoryItem"]
SerializationHook = Callable[["MemoryItem"], JSON]


@dataclass(frozen=True)
class MemoryItem:
    """A single memory item (immutable)."""

    scope: MemoryScope
    key: str
    value: JSON
    confidence: Confidence = Confidence(1.0)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    ttl: timedelta | None = None  # Time-to-live
    expires_at: datetime | None = None  # Explicit expiration time

    def __post_init__(self) -> None:
        """Set expires_at from ttl if not provided."""
        if self.ttl and not self.expires_at:
            # Work around frozen dataclass
            object.__setattr__(self, "expires_at", self.created_at + self.ttl)

    @property
    def full_key(self) -> str:
        """Full key including scope."""
        return f"{self.scope.value}:{self.key}"

    @property
    def is_expired(self) -> bool:
        """Check if this item has expired."""
        if self.expires_at is None:
            return False
        return utc_now() >= self.expires_at

    @property
    def remaining_ttl(self) -> timedelta | None:
        """Get remaining time-to-live, or None if no expiration."""
        if self.expires_at is None:
            return None
        remaining = self.expires_at - utc_now()
        return remaining if remaining.total_seconds() > 0 else timedelta(0)

    def with_update(self, value: JSON, confidence: Confidence | None = None) -> MemoryItem:
        """Create updated memory item."""
        return MemoryItem(
            scope=self.scope,
            key=self.key,
            value=value,
            confidence=confidence or self.confidence,
            created_at=self.created_at,
            updated_at=utc_now(),
            ttl=self.ttl,
            expires_at=self.expires_at,
        )

    def with_ttl(self, ttl: timedelta) -> MemoryItem:
        """Create a copy with a new TTL."""
        return MemoryItem(
            scope=self.scope,
            key=self.key,
            value=self.value,
            confidence=self.confidence,
            created_at=self.created_at,
            updated_at=self.updated_at,
            ttl=ttl,
            expires_at=utc_now() + ttl,
        )

    def without_expiration(self) -> MemoryItem:
        """Create a copy without expiration."""
        return MemoryItem(
            scope=self.scope,
            key=self.key,
            value=self.value,
            confidence=self.confidence,
            created_at=self.created_at,
            updated_at=self.updated_at,
            ttl=None,
            expires_at=None,
        )


class MemoryStore(ABC):
    """Abstract memory store with hook support."""

    def __init__(self) -> None:
        self._redaction_hook: RedactionHook | None = None
        self._serialization_hook: SerializationHook | None = None

    def set_redaction_hook(self, hook: RedactionHook | None) -> None:
        """
        Set a hook to redact sensitive data before returning items.

        The hook receives a MemoryItem and should return a redacted copy.
        Use this to remove PII, secrets, etc. from memory items.

        Example:
            def redact_pii(item: MemoryItem) -> MemoryItem:
                value = dict(item.value)
                if "ssn" in value:
                    value["ssn"] = "***-**-****"
                return MemoryItem(..., value=value)

            store.set_redaction_hook(redact_pii)
        """
        self._redaction_hook = hook

    def set_serialization_hook(self, hook: SerializationHook | None) -> None:
        """
        Set a hook for custom serialization.

        The hook receives a MemoryItem and should return JSON-serializable data.
        Use this for custom export formats, logging, etc.

        Example:
            def serialize_for_export(item: MemoryItem) -> JSON:
                return {
                    "key": item.full_key,
                    "value": item.value,
                    "expires": item.expires_at.isoformat() if item.expires_at else None,
                }

            store.set_serialization_hook(serialize_for_export)
        """
        self._serialization_hook = hook

    def _apply_redaction(self, item: MemoryItem | None) -> MemoryItem | None:
        """Apply redaction hook if set."""
        if item is None or self._redaction_hook is None:
            return item
        return self._redaction_hook(item)

    def serialize_item(self, item: MemoryItem) -> JSON:
        """Serialize an item using the hook, or default serialization."""
        if self._serialization_hook:
            return self._serialization_hook(item)
        return {
            "scope": item.scope.value,
            "key": item.key,
            "value": item.value,
            "confidence": float(item.confidence),
            "created_at": item.created_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
            "expires_at": item.expires_at.isoformat() if item.expires_at else None,
        }

    @abstractmethod
    async def get(self, scope: MemoryScope, key: str) -> MemoryItem | None: ...

    @abstractmethod
    async def set(self, item: MemoryItem) -> None: ...

    @abstractmethod
    async def delete(self, scope: MemoryScope, key: str) -> bool: ...

    @abstractmethod
    async def list_by_scope(self, scope: MemoryScope) -> tuple[MemoryItem, ...]: ...

    async def cleanup_expired(self) -> int:
        """
        Remove all expired items from the store.

        Returns:
            Number of items removed
        """
        # Default implementation - subclasses may override for efficiency
        return 0
        ...


class InMemoryStore(MemoryStore):
    """In-memory store for testing or session-scoped memory."""

    def __init__(self) -> None:
        super().__init__()
        self._data: dict[str, MemoryItem] = {}

    async def get(self, scope: MemoryScope, key: str) -> MemoryItem | None:
        item = self._data.get(f"{scope.value}:{key}")

        # Check expiration (lazy cleanup)
        if item and item.is_expired:
            await self.delete(scope, key)
            return None

        # Apply redaction hook
        return self._apply_redaction(item)

    async def set(self, item: MemoryItem) -> None:
        self._data[item.full_key] = item

    async def delete(self, scope: MemoryScope, key: str) -> bool:
        full_key = f"{scope.value}:{key}"
        if full_key in self._data:
            del self._data[full_key]
            return True
        return False

    async def list_by_scope(self, scope: MemoryScope) -> tuple[MemoryItem, ...]:
        prefix = f"{scope.value}:"
        items = []
        for key, item in list(self._data.items()):
            if not key.startswith(prefix):
                continue
            # Skip expired items
            if item.is_expired:
                await self.delete(item.scope, item.key)
                continue
            items.append(self._apply_redaction(item))
        return tuple(i for i in items if i is not None)

    async def search(
        self,
        query: str,
        scope: MemoryScope | None = None,
        limit: int = 10,
    ) -> tuple[MemoryItem, ...]:
        """Simple text search."""
        q = query.lower()
        results = []
        for item in list(self._data.values()):
            # Skip expired items
            if item.is_expired:
                await self.delete(item.scope, item.key)
                continue
            if scope and item.scope != scope:
                continue
            if q in str(item.value).lower() or q in item.key.lower():
                redacted = self._apply_redaction(item)
                if redacted:
                    results.append(redacted)
                if len(results) >= limit:
                    break
        return tuple(results)

    async def cleanup_expired(self) -> int:
        """Remove all expired items from the store."""
        expired_keys = [key for key, item in self._data.items() if item.is_expired]
        for key in expired_keys:
            del self._data[key]
        return len(expired_keys)

    async def get_all_expired(self) -> tuple[MemoryItem, ...]:
        """Get all expired items (for inspection before cleanup)."""
        return tuple(item for item in self._data.values() if item.is_expired)

    def clear(self) -> None:
        """Clear all items from the store."""
        self._data.clear()
