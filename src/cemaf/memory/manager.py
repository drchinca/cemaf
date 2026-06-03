"""MemoryManager — unified orchestrator for semantic + episodic memory.

The single entry point for agents that need to remember things across calls.
Agents do not talk to `MemoryStore` / `SemanticMemoryStore` / `EpisodicStore`
directly; they call `manager.remember()`, `manager.recall()`,
`manager.start_episode()`, etc., and the manager composes the right
backends behind the scenes.

Composition:
- A `MemoryStore` (SQLite, InMemory, or BYO) for scoped key-value persistence
- A `SemanticMemoryStore` for vector-similarity recall
- An `EpisodicStore` for turn-by-turn session history
- An optional `MemoryDeduplicator` for near-duplicate resolution on write
- An optional `EventBus` for emitting `MEMORY_*` events to subscribers
  (audit trail, knowledge graph refresh, etc.)

Scopes (in `MemoryScope` enum) — the isolation boundaries:
- `SESSION` — per-run memory; disposed at run end via `SessionManager`
- `PROJECT` — persistent across runs within a project
- `TENANT` — cross-project durable memory
- `GLOBAL` — framework-wide (use sparingly)

Protocol-first — `MemoryManager` is a `@runtime_checkable` Protocol so you
can drop in your own implementation (Redis-backed, Postgres, graph DB)
via `RuntimeServices(memory_manager=MyMemoryManager())` without forking.

Factory:
    from cemaf.memory.factories import create_memory_manager

    manager = create_memory_manager(
        memory_store=SqliteMemoryStore(db_path="memory.db"),
        embedding_provider=OpenAIEmbeddingProvider(...),
        event_bus=bus,
    )

Then inject via `RuntimeServices(memory_manager=manager, session_manager=...)`.
"""

from typing import Protocol, runtime_checkable

from cemaf.core.enums import MemoryScope
from cemaf.core.types import JSON, Confidence
from cemaf.events.protocols import Event, EventBus, EventType
from cemaf.memory.base import MemoryItem
from cemaf.memory.deduplication import MemoryDeduplicator
from cemaf.memory.episodic import Episode, EpisodicEvent, EpisodicStore
from cemaf.memory.semantic import MemoryQuery, MemorySearchResult, SemanticMemoryStore


@runtime_checkable
class MemoryManager(Protocol):
    """Unified API for agents to interact with memory."""

    # Semantic memory
    async def remember(
        self,
        scope: MemoryScope,
        key: str,
        value: JSON,
        *,
        confidence: float = 1.0,
        content_for_embedding: str | None = None,
    ) -> MemoryItem: ...

    async def recall(self, query: MemoryQuery) -> tuple[MemorySearchResult, ...]: ...

    async def recall_by_key(
        self,
        scope: MemoryScope,
        key: str,
    ) -> MemoryItem | None: ...

    async def forget(self, scope: MemoryScope, key: str) -> bool: ...

    # Episodic memory
    async def start_episode(self, session_id: str) -> Episode: ...

    async def record_event(
        self,
        episode_id: str,
        event: EpisodicEvent,
    ) -> None: ...

    async def end_episode(self, episode_id: str) -> Episode: ...

    async def get_recent_history(
        self,
        session_id: str,
        *,
        limit: int = 20,
    ) -> tuple[EpisodicEvent, ...]: ...

    # Lifecycle
    async def cleanup(self) -> int: ...


class DefaultMemoryManager:
    """Default implementation composing semantic + episodic stores."""

    def __init__(
        self,
        *,
        semantic_store: SemanticMemoryStore,
        episodic_store: EpisodicStore,
        event_bus: EventBus | None = None,
        deduplicator: MemoryDeduplicator | None = None,
    ) -> None:
        self._semantic = semantic_store
        self._episodic = episodic_store
        self._event_bus = event_bus
        self._deduplicator = deduplicator

    # -- Semantic memory -----------------------------------------------------

    async def remember(
        self,
        scope: MemoryScope,
        key: str,
        value: JSON,
        *,
        confidence: float = 1.0,
        content_for_embedding: str | None = None,
    ) -> MemoryItem:
        """Store a memory item with optional deduplication."""
        item = MemoryItem(
            scope=scope,
            key=key,
            value=value,
            confidence=Confidence(confidence),
        )

        if self._deduplicator is not None:
            matches = await self._deduplicator.find_duplicates(candidate=item)
            result = await self._deduplicator.resolve(candidate=item, matches=matches)
            if result.skipped:
                return item
            item = result.item

        await self._semantic.store(
            item=item,
            content_for_embedding=content_for_embedding,
        )
        await self._emit(
            event_type=EventType.MEMORY_ITEM_SET,
            payload={"scope": scope.value, "key": key},
        )
        return item

    async def recall(
        self,
        query: MemoryQuery,
    ) -> tuple[MemorySearchResult, ...]:
        """Search memory using semantic similarity and temporal decay."""
        return await self._semantic.search(query=query)

    async def recall_by_key(
        self,
        scope: MemoryScope,
        key: str,
    ) -> MemoryItem | None:
        """Direct key-value lookup."""
        return await self._semantic.get(scope=scope, key=key)

    async def forget(self, scope: MemoryScope, key: str) -> bool:
        """Delete a memory item."""
        return await self._semantic.delete(scope=scope, key=key)

    # -- Episodic memory -----------------------------------------------------

    async def start_episode(self, session_id: str) -> Episode:
        """Start a new episode for the session."""
        return await self._episodic.start_episode(session_id=session_id)

    async def record_event(
        self,
        episode_id: str,
        event: EpisodicEvent,
    ) -> None:
        """Record an event in the current episode."""
        await self._episodic.append_event(episode_id=episode_id, event=event)

    async def end_episode(self, episode_id: str) -> Episode:
        """Close the current episode."""
        return await self._episodic.close_episode(episode_id=episode_id)

    async def get_recent_history(
        self,
        session_id: str,
        *,
        limit: int = 20,
    ) -> tuple[EpisodicEvent, ...]:
        """Get recent events from the session."""
        return await self._episodic.get_recent_events(
            session_id=session_id,
            limit=limit,
        )

    # -- Lifecycle -----------------------------------------------------------

    async def cleanup(self) -> int:
        """Clean up expired items."""
        removed = await self._semantic.cleanup_expired()
        await self._emit(
            event_type=EventType.MEMORY_CLEANUP,
            payload={"removed": removed},
        )
        return removed

    # -- Internal ------------------------------------------------------------

    async def _emit(
        self,
        *,
        event_type: EventType,
        payload: JSON,
    ) -> None:
        """Emit an event if event bus is configured."""
        if self._event_bus is None:
            return
        event = Event.create(
            type=event_type,
            payload=payload,
            source="memory_manager",
        )
        await self._event_bus.publish(event=event)
