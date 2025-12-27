"""
Memory base classes and in-memory implementation.

Memory items have:
- Scope (brand, project, etc.)
- Key (unique within scope)
- Value (JSON-serializable)
- Confidence score
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from cemaf.core.types import JSON, Confidence
from cemaf.core.enums import MemoryScope
from cemaf.core.utils import utc_now


@dataclass(frozen=True)
class MemoryItem:
    """A single memory item (immutable)."""
    
    scope: MemoryScope
    key: str
    value: JSON
    confidence: Confidence = Confidence(1.0)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    
    @property
    def full_key(self) -> str:
        """Full key including scope."""
        return f"{self.scope.value}:{self.key}"
    
    def with_update(self, value: JSON, confidence: Confidence | None = None) -> MemoryItem:
        """Create updated memory item."""
        return MemoryItem(
            scope=self.scope,
            key=self.key,
            value=value,
            confidence=confidence or self.confidence,
            created_at=self.created_at,
            updated_at=utc_now(),
        )


class MemoryStore(ABC):
    """Abstract memory store."""
    
    @abstractmethod
    async def get(self, scope: MemoryScope, key: str) -> MemoryItem | None:
        ...
    
    @abstractmethod
    async def set(self, item: MemoryItem) -> None:
        ...
    
    @abstractmethod
    async def delete(self, scope: MemoryScope, key: str) -> bool:
        ...
    
    @abstractmethod
    async def list_by_scope(self, scope: MemoryScope) -> tuple[MemoryItem, ...]:
        ...


class InMemoryStore(MemoryStore):
    """In-memory store for testing or session-scoped memory."""
    
    def __init__(self) -> None:
        self._data: dict[str, MemoryItem] = {}
    
    async def get(self, scope: MemoryScope, key: str) -> MemoryItem | None:
        return self._data.get(f"{scope.value}:{key}")
    
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
        return tuple(item for key, item in self._data.items() if key.startswith(prefix))
    
    async def search(self, query: str, scope: MemoryScope | None = None, limit: int = 10) -> tuple[MemoryItem, ...]:
        """Simple text search."""
        q = query.lower()
        results = []
        for item in self._data.values():
            if scope and item.scope != scope:
                continue
            if q in str(item.value).lower() or q in item.key.lower():
                results.append(item)
                if len(results) >= limit:
                    break
        return tuple(results)
    
    def clear(self) -> None:
        self._data.clear()
