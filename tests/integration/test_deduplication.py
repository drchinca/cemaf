"""Integration tests for memory deduplication wired into MemoryManager."""

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.memory.base import InMemoryStore
from cemaf.memory.deduplication import SemanticDeduplicator
from cemaf.memory.episodic import InMemoryEpisodicStore
from cemaf.memory.manager import DefaultMemoryManager
from cemaf.memory.scoring import TemporalDecayScorer
from cemaf.memory.semantic import DefaultSemanticMemoryStore, MemoryQuery
from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider


def _wire_stack_with_dedup() -> tuple[DefaultMemoryManager, DefaultSemanticMemoryStore]:
    """Wire full stack with deduplicator."""
    store = InMemoryStore()
    embedding_provider = MockEmbeddingProvider()
    scorer = TemporalDecayScorer()

    semantic_store = DefaultSemanticMemoryStore(
        memory_store=store,
        vector_store=InMemoryVectorStore(embedding_provider=embedding_provider),
        embedding_provider=embedding_provider,
        scorer=scorer,
    )
    deduplicator = SemanticDeduplicator(
        semantic_store=semantic_store,
        similarity_threshold=0.85,
    )
    episodic_store = InMemoryEpisodicStore()

    manager = DefaultMemoryManager(
        semantic_store=semantic_store,
        episodic_store=episodic_store,
        deduplicator=deduplicator,
    )
    return manager, semantic_store


class TestRememberWithDeduplication:
    """Integration: deduplicator wired into manager.remember()."""

    @pytest.mark.asyncio
    async def test_skips_exact_key_duplicate(self) -> None:
        """Remember same scope:key twice → second call detects exact key, merges (stores once)."""
        manager, semantic_store = _wire_stack_with_dedup()

        await manager.remember(
            scope=MemoryScope.PROJECT,
            key="brand-tone",
            value={"tone": "professional"},
            confidence=0.9,
        )
        await manager.remember(
            scope=MemoryScope.PROJECT,
            key="brand-tone",
            value={"tone": "casual"},
            confidence=0.5,
        )

        # The exact key match triggers merge (higher confidence wins)
        results = await manager.recall(
            query=MemoryQuery(scope=MemoryScope.PROJECT, limit=100),
        )
        brand_tone_items = [r for r in results if r.item.key == "brand-tone"]
        assert len(brand_tone_items) == 1

    @pytest.mark.asyncio
    async def test_novel_items_stored_normally(self) -> None:
        """Different items pass dedup and both get stored."""
        manager, _ = _wire_stack_with_dedup()

        await manager.remember(
            scope=MemoryScope.PROJECT,
            key="item-a",
            value={"data": "alpha"},
        )
        await manager.remember(
            scope=MemoryScope.PROJECT,
            key="item-b",
            value={"data": "beta"},
        )

        results = await manager.recall(
            query=MemoryQuery(scope=MemoryScope.PROJECT, limit=100),
        )
        keys = {r.item.key for r in results}
        assert "item-a" in keys
        assert "item-b" in keys

    @pytest.mark.asyncio
    async def test_without_deduplicator_stores_normally(self) -> None:
        """Manager without deduplicator stores everything."""
        store = InMemoryStore()
        embedding_provider = MockEmbeddingProvider()
        scorer = TemporalDecayScorer()

        semantic_store = DefaultSemanticMemoryStore(
            memory_store=store,
            vector_store=InMemoryVectorStore(embedding_provider=embedding_provider),
            embedding_provider=embedding_provider,
            scorer=scorer,
        )
        manager = DefaultMemoryManager(
            semantic_store=semantic_store,
            episodic_store=InMemoryEpisodicStore(),
        )

        await manager.remember(
            scope=MemoryScope.PROJECT,
            key="item",
            value={"v": 1},
        )
        item = await manager.recall_by_key(scope=MemoryScope.PROJECT, key="item")
        assert item is not None
