"""
Integration tests: file-backed persistence + cross-session memory promotion.

Based on: https://blog.langchain.com/your-harness-your-memory/
Key ideas implemented:
- Long-term memory ownership via JsonFileMemoryStore (persists across restarts)
- Data flywheel: high-confidence SESSION items promoted to PROJECT scope on dispose()

All tests use real implementations — no mocks.
"""

from pathlib import Path

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.memory.base import InMemoryStore, JsonFileMemoryStore
from cemaf.memory.compaction import SimpleMemoryCompactor
from cemaf.memory.episodic import InMemoryEpisodicStore
from cemaf.memory.factories import create_memory_store
from cemaf.memory.manager import DefaultMemoryManager
from cemaf.memory.scoring import TemporalDecayScorer
from cemaf.memory.semantic import DefaultSemanticMemoryStore, MemoryQuery
from cemaf.memory.session import DefaultSessionManager
from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wire_stack(
    memory_store: InMemoryStore | JsonFileMemoryStore | None = None,
) -> tuple[DefaultMemoryManager, DefaultSessionManager]:
    embedding_provider = MockEmbeddingProvider()
    scorer = TemporalDecayScorer()

    semantic_store = DefaultSemanticMemoryStore(
        memory_store=memory_store or InMemoryStore(),
        vector_store=InMemoryVectorStore(embedding_provider=embedding_provider),
        embedding_provider=embedding_provider,
        scorer=scorer,
    )
    episodic_store = InMemoryEpisodicStore()
    manager = DefaultMemoryManager(
        semantic_store=semantic_store,
        episodic_store=episodic_store,
    )
    compactor = SimpleMemoryCompactor(scorer=scorer)
    session_mgr = DefaultSessionManager(memory_manager=manager, compactor=compactor)
    return manager, session_mgr


# ---------------------------------------------------------------------------
# JsonFileMemoryStore: end-to-end persistence round-trip
# ---------------------------------------------------------------------------


class TestFileBackedPersistenceRoundTrip:
    """Memories stored via a file-backed store survive process restarts."""

    @pytest.mark.asyncio
    async def test_project_memories_survive_restart(self, tmp_path: Path) -> None:
        """Store PROJECT-scoped memories; reload from file; they are retrievable."""
        path = tmp_path / "mem.json"

        # --- "First process": store memories ---
        store1 = JsonFileMemoryStore(path=path)
        manager1, _ = _wire_stack(store1)

        await manager1.remember(
            scope=MemoryScope.PROJECT,
            key="style_guide",
            value={"tone": "professional", "language": "en"},
        )
        await manager1.remember(
            scope=MemoryScope.PROJECT,
            key="target_audience",
            value={"segment": "enterprise"},
        )

        # --- "Second process": new store + manager, same file ---
        store2 = JsonFileMemoryStore(path=path)
        manager2, _ = _wire_stack(store2)

        results = await manager2.recall(query=MemoryQuery(scope=MemoryScope.PROJECT, limit=10))
        keys = {r.item.key for r in results}
        assert "style_guide" in keys
        assert "target_audience" in keys

    @pytest.mark.asyncio
    async def test_file_backed_store_via_factory(self, tmp_path: Path) -> None:
        """create_memory_store(backend='json_file') wires correctly."""
        path = tmp_path / "factory_mem.json"
        store = create_memory_store(backend="json_file", file_path=str(path))

        assert isinstance(store, JsonFileMemoryStore)

        manager, _ = _wire_stack(store)
        await manager.remember(scope=MemoryScope.TENANT, key="brand", value={"v": 1})

        # Reload
        store2 = create_memory_store(backend="json_file", file_path=str(path))
        manager2, _ = _wire_stack(store2)
        result = await manager2.recall(query=MemoryQuery(scope=MemoryScope.TENANT, limit=10))
        assert len(result) == 1
        assert result[0].item.key == "brand"


# ---------------------------------------------------------------------------
# Cross-session memory promotion (data flywheel)
# ---------------------------------------------------------------------------


class TestCrossSessionPromotion:
    """High-confidence SESSION items are promoted to long-term scope on dispose()."""

    @pytest.mark.asyncio
    async def test_high_confidence_items_promoted_to_project(self) -> None:
        manager, session_mgr = _wire_stack()

        await session_mgr.bootstrap(session_id="s1")
        # High confidence — should be promoted
        await session_mgr.ingest(
            "s1",
            key="user_preference",
            value={"theme": "dark"},
            confidence=0.9,
        )
        # Low confidence — should NOT be promoted
        await session_mgr.ingest(
            "s1",
            key="speculative_guess",
            value={"guess": "maybe"},
            confidence=0.3,
        )

        await session_mgr.dispose("s1", promote_to=MemoryScope.PROJECT)

        # PROJECT scope should contain the promoted item
        project_items = await manager.recall(query=MemoryQuery(scope=MemoryScope.PROJECT, limit=100))
        promoted_keys = {r.item.key for r in project_items}
        assert "user_preference" in promoted_keys
        assert "speculative_guess" not in promoted_keys

    @pytest.mark.asyncio
    async def test_promoted_items_survive_file_restart(self, tmp_path: Path) -> None:
        """Promotion + file persistence: learnings from session outlive the process."""
        path = tmp_path / "long_term.json"
        store = JsonFileMemoryStore(path=path)
        manager, session_mgr = _wire_stack(store)

        await session_mgr.bootstrap(session_id="s1")
        await session_mgr.ingest(
            "s1",
            key="campaign_insight",
            value={"insight": "short headlines perform better"},
            confidence=0.95,
        )
        await session_mgr.dispose("s1", promote_to=MemoryScope.PROJECT)

        # New process — reload from file
        store2 = JsonFileMemoryStore(path=path)
        manager2, _ = _wire_stack(store2)
        results = await manager2.recall(query=MemoryQuery(scope=MemoryScope.PROJECT, limit=10))
        keys = {r.item.key for r in results}
        assert "campaign_insight" in keys

    @pytest.mark.asyncio
    async def test_no_promotion_when_promote_to_is_none(self) -> None:
        manager, session_mgr = _wire_stack()

        await session_mgr.bootstrap(session_id="s1")
        await session_mgr.ingest("s1", key="ephemeral", value={"x": 1}, confidence=1.0)
        # Dispose without promotion
        await session_mgr.dispose("s1")

        project_items = await manager.recall(query=MemoryQuery(scope=MemoryScope.PROJECT, limit=100))
        assert all(r.item.key != "ephemeral" for r in project_items)

    @pytest.mark.asyncio
    async def test_promotion_custom_confidence_threshold(self) -> None:
        manager, session_mgr = _wire_stack()

        await session_mgr.bootstrap(session_id="s1")
        await session_mgr.ingest("s1", key="medium", value={}, confidence=0.6)
        await session_mgr.ingest("s1", key="high", value={}, confidence=0.95)

        # Only items >= 0.7 should be promoted
        await session_mgr.dispose("s1", promote_to=MemoryScope.PROJECT, promotion_min_confidence=0.7)

        project_items = await manager.recall(query=MemoryQuery(scope=MemoryScope.PROJECT, limit=100))
        promoted_keys = {r.item.key for r in project_items}
        assert "high" in promoted_keys
        assert "medium" not in promoted_keys

    @pytest.mark.asyncio
    async def test_dispose_transitions_session_to_disposed(self) -> None:
        """dispose() succeeds and the session state is marked DISPOSED."""
        from cemaf.memory.session import SessionPhase

        _, session_mgr = _wire_stack()

        await session_mgr.bootstrap(session_id="s1")
        await session_mgr.ingest("s1", key="temp", value={"x": 1})
        await session_mgr.dispose("s1", promote_to=MemoryScope.PROJECT)

        state = await session_mgr.get_state("s1")
        assert state is not None
        assert state.phase == SessionPhase.DISPOSED
