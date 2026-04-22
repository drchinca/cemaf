"""Integration tests for TieredMemoryStore with progressive retrieval."""

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.core.types import Confidence
from cemaf.memory.base import InMemoryStore, MemoryItem
from cemaf.memory.scoring import TemporalDecayScorer
from cemaf.memory.semantic import DefaultSemanticMemoryStore, MemoryQuery
from cemaf.memory.tiered import TruncationTierGenerator
from cemaf.memory.tiered_store import TieredMemoryStore
from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider


def _wire_tiered_store() -> TieredMemoryStore:
    """Wire up a real tiered store for testing."""
    store = InMemoryStore()
    embedding_provider = MockEmbeddingProvider()
    scorer = TemporalDecayScorer()

    semantic_store = DefaultSemanticMemoryStore(
        memory_store=store,
        vector_store=InMemoryVectorStore(embedding_provider=embedding_provider),
        embedding_provider=embedding_provider,
        scorer=scorer,
    )

    return TieredMemoryStore(
        semantic_store=semantic_store,
        tier_generator=TruncationTierGenerator(),
    )


class TestStoreWithTiersAndSearch:
    """Integration: store items with tiers and retrieve progressively."""

    @pytest.mark.asyncio
    async def test_store_and_retrieve_tiered_items(self) -> None:
        """Store 20 items → progressive_search → verify narrowing."""
        tiered_store = _wire_tiered_store()

        # Store 20 items
        for i in range(20):
            item = MemoryItem(
                scope=MemoryScope.PROJECT,
                key=f"item-{i}",
                value={"content": f"Some content about topic {i}" * 50},
                confidence=Confidence(0.5 + (i * 0.02)),
            )
            await tiered_store.store_with_tiers(item=item)

        # Progressive search: should narrow from 50 → 10 → 5
        results = await tiered_store.progressive_search(
            query=MemoryQuery(
                text="content about topic",
                scope=MemoryScope.PROJECT,
                limit=50,
            ),
            l0_limit=50,
            l1_limit=10,
            l2_limit=5,
        )

        assert len(results) <= 5
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_tier_cache_populated(self) -> None:
        """Store an item → tier cache has the tiered version."""
        tiered_store = _wire_tiered_store()

        item = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="cached-item",
            value={"data": "test value"},
        )
        await tiered_store.store_with_tiers(item=item)

        cached = tiered_store.get_tiered(full_key=item.full_key)
        assert cached is not None
        assert cached.item.key == "cached-item"
        assert cached.l0_token_count > 0

    @pytest.mark.asyncio
    async def test_progressive_search_returns_fewer_than_flat(self) -> None:
        """Progressive search returns at most l2_limit results."""
        tiered_store = _wire_tiered_store()

        for i in range(15):
            item = MemoryItem(
                scope=MemoryScope.PROJECT,
                key=f"doc-{i}",
                value={"text": f"Document content {i}" * 100},
            )
            await tiered_store.store_with_tiers(item=item)

        results = await tiered_store.progressive_search(
            query=MemoryQuery(
                text="document content",
                scope=MemoryScope.PROJECT,
            ),
            l0_limit=15,
            l1_limit=8,
            l2_limit=3,
        )

        assert len(results) <= 3
