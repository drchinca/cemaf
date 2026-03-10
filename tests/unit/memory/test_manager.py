"""Tests for memory manager."""

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.core.utils import utc_now
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import EventType
from cemaf.memory.base import InMemoryStore
from cemaf.memory.episodic import EpisodicEvent, InMemoryEpisodicStore
from cemaf.memory.manager import DefaultMemoryManager, MemoryManager
from cemaf.memory.scoring import TemporalDecayScorer
from cemaf.memory.semantic import DefaultSemanticMemoryStore, MemoryQuery
from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_manager(
    *,
    with_event_bus: bool = False,
) -> tuple[DefaultMemoryManager, InMemoryEventBus | None]:
    """Create a fully wired memory manager."""
    embedding_provider = MockEmbeddingProvider()
    semantic_store = DefaultSemanticMemoryStore(
        memory_store=InMemoryStore(),
        vector_store=InMemoryVectorStore(embedding_provider=embedding_provider),
        embedding_provider=embedding_provider,
        scorer=TemporalDecayScorer(),
    )
    episodic_store = InMemoryEpisodicStore()
    event_bus = InMemoryEventBus() if with_event_bus else None

    manager = DefaultMemoryManager(
        semantic_store=semantic_store,
        episodic_store=episodic_store,
        event_bus=event_bus,
    )
    return manager, event_bus


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_implements_memory_manager(self) -> None:
        manager, _ = _make_manager()
        assert isinstance(manager, MemoryManager)


# ---------------------------------------------------------------------------
# Semantic memory — remember / recall / forget
# ---------------------------------------------------------------------------


class TestSemanticMemory:
    @pytest.mark.asyncio
    async def test_remember_and_recall_by_key(self) -> None:
        manager, _ = _make_manager()
        item = await manager.remember(
            scope=MemoryScope.BRAND,
            key="company",
            value={"name": "Acme"},
        )
        assert item.key == "company"

        recalled = await manager.recall_by_key(
            scope=MemoryScope.BRAND,
            key="company",
        )
        assert recalled is not None
        assert recalled.value == {"name": "Acme"}

    @pytest.mark.asyncio
    async def test_recall_nonexistent(self) -> None:
        manager, _ = _make_manager()
        result = await manager.recall_by_key(
            scope=MemoryScope.BRAND,
            key="nonexistent",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_recall_with_query(self) -> None:
        manager, _ = _make_manager()
        await manager.remember(
            scope=MemoryScope.BRAND,
            key="product",
            value={"name": "Widget"},
        )
        results = await manager.recall(
            query=MemoryQuery(text="Widget", limit=5),
        )
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_forget(self) -> None:
        manager, _ = _make_manager()
        await manager.remember(
            scope=MemoryScope.SESSION,
            key="temp",
            value={"data": "temporary"},
        )
        deleted = await manager.forget(scope=MemoryScope.SESSION, key="temp")
        assert deleted is True
        result = await manager.recall_by_key(scope=MemoryScope.SESSION, key="temp")
        assert result is None

    @pytest.mark.asyncio
    async def test_forget_nonexistent(self) -> None:
        manager, _ = _make_manager()
        deleted = await manager.forget(scope=MemoryScope.SESSION, key="nope")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_remember_with_confidence(self) -> None:
        manager, _ = _make_manager()
        item = await manager.remember(
            scope=MemoryScope.BRAND,
            key="fact",
            value={"statement": "verified"},
            confidence=0.9,
        )
        assert float(item.confidence) == 0.9


# ---------------------------------------------------------------------------
# Episodic memory
# ---------------------------------------------------------------------------


class TestEpisodicMemory:
    @pytest.mark.asyncio
    async def test_episode_lifecycle(self) -> None:
        manager, _ = _make_manager()
        episode = await manager.start_episode(session_id="sess-1")
        assert episode.ended_at is None

        event = EpisodicEvent(
            timestamp=utc_now(),
            event_type="agent.completed",
            actor="agent-1",
            action="generate",
        )
        await manager.record_event(episode_id=episode.id, event=event)

        closed = await manager.end_episode(episode_id=episode.id)
        assert closed.ended_at is not None

    @pytest.mark.asyncio
    async def test_get_recent_history(self) -> None:
        manager, _ = _make_manager()
        episode = await manager.start_episode(session_id="sess-1")
        for i in range(3):
            await manager.record_event(
                episode_id=episode.id,
                event=EpisodicEvent(
                    timestamp=utc_now(),
                    event_type="test",
                    actor="system",
                    action=f"action_{i}",
                ),
            )
        history = await manager.get_recent_history(session_id="sess-1")
        assert len(history) == 3


# ---------------------------------------------------------------------------
# EventBus integration
# ---------------------------------------------------------------------------


class TestEventBusIntegration:
    @pytest.mark.asyncio
    async def test_remember_emits_event(self) -> None:
        manager, event_bus = _make_manager(with_event_bus=True)
        assert event_bus is not None

        events_received: list = []
        event_bus.subscribe(
            event_type=EventType.MEMORY_ITEM_SET,
            handler=lambda e: events_received.append(e),
        )

        await manager.remember(
            scope=MemoryScope.BRAND,
            key="test",
            value={"data": "test"},
        )
        assert len(events_received) == 1
        assert events_received[0].type == EventType.MEMORY_ITEM_SET.value

    @pytest.mark.asyncio
    async def test_cleanup_emits_event(self) -> None:
        manager, event_bus = _make_manager(with_event_bus=True)
        assert event_bus is not None

        events_received: list = []
        event_bus.subscribe(
            event_type=EventType.MEMORY_CLEANUP,
            handler=lambda e: events_received.append(e),
        )

        await manager.cleanup()
        assert len(events_received) == 1

    @pytest.mark.asyncio
    async def test_no_event_bus_is_fine(self) -> None:
        manager, _ = _make_manager(with_event_bus=False)
        # Should not raise, and should still store memory correctly
        item = await manager.remember(
            scope=MemoryScope.BRAND,
            key="test",
            value={"data": "test"},
        )
        assert item.key == "test"
        assert item.value == {"data": "test"}

        removed = await manager.cleanup()
        assert removed >= 0


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_returns_count(self) -> None:
        manager, _ = _make_manager()
        removed = await manager.cleanup()
        assert removed >= 0
