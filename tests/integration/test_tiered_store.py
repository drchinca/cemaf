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


class TestProgressiveSearchCompactedReducesPerItemCost:
    """The property the audit found untested: tier-aware retrieval returns
    CHEAPER per-item content for lower-ranked items, not full content for all."""

    @pytest.mark.asyncio
    async def test_lower_ranked_items_cost_less_than_full(self) -> None:
        tiered_store = _wire_tiered_store()

        # Store enough distinct items to span all three tiers.
        for i in range(12):
            item = MemoryItem(
                scope=MemoryScope.PROJECT,
                key=f"doc-{i}",
                value={"text": f"Distinct document {i} " + ("body " * 200)},
                confidence=Confidence(1.0),
            )
            await tiered_store.store_with_tiers(item=item)

        compacted = await tiered_store.progressive_search_compacted(
            query=MemoryQuery(text="document", scope=MemoryScope.PROJECT),
            l0_limit=12,
            l1_limit=4,
            l2_limit=2,
        )
        assert len(compacted) > 6, "expected breadth across tiers"

        # The full (L2) items must genuinely cost more than the abstract (L0)
        # ones — proving tiers reduce per-item token cost, not just count.
        full = [c.compacted_token_count for c in compacted if c.level.value == "full"]
        abstracts = [c.compacted_token_count for c in compacted if c.level.value == "metadata"]
        assert full, "expected some full-content (L2) items"
        assert abstracts, "expected some L0 abstract items"
        assert max(abstracts) < max(full), "L0 abstracts must be cheaper than L2 full content"

    @pytest.mark.asyncio
    async def test_total_cost_less_than_loading_all_at_full(self) -> None:
        tiered_store = _wire_tiered_store()
        for i in range(10):
            item = MemoryItem(
                scope=MemoryScope.PROJECT,
                key=f"d-{i}",
                value={"text": f"Distinct content {i} " + ("filler " * 200)},
                confidence=Confidence(1.0),
            )
            await tiered_store.store_with_tiers(item=item)

        compacted = await tiered_store.progressive_search_compacted(
            query=MemoryQuery(text="content", scope=MemoryScope.PROJECT),
            l0_limit=10,
            l1_limit=3,
            l2_limit=2,
        )
        tiered_total = sum(c.compacted_token_count for c in compacted)
        full_total = sum(c.original_token_count for c in compacted)
        # Tiering the lower-ranked items saves real tokens vs all-at-full.
        assert tiered_total < full_total
