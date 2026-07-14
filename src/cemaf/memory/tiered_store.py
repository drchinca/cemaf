"""Tier-aware memory store with progressive retrieval."""

from cemaf.memory.base import MemoryItem
from cemaf.memory.compaction import CompactedMemory, CompactionLevel
from cemaf.memory.semantic import MemoryQuery, MemorySearchResult, SemanticMemoryStore
from cemaf.memory.tiered import LoadingTier, TieredMemoryItem, TierGenerator


class TieredMemoryStore:
    """Wraps SemanticMemoryStore with tier-aware progressive retrieval."""

    def __init__(
        self,
        *,
        semantic_store: SemanticMemoryStore,
        tier_generator: TierGenerator,
    ) -> None:
        self._store = semantic_store
        self._generator = tier_generator
        self._tier_cache: dict[str, TieredMemoryItem] = {}

    async def store_with_tiers(
        self,
        item: MemoryItem,
        *,
        content_for_embedding: str | None = None,
    ) -> TieredMemoryItem:
        """Generate tiers, store in underlying store, cache tiered item."""
        tiered = await self._generator.generate_tiers(item=item)
        await self._store.store(item=item, content_for_embedding=content_for_embedding)
        self._tier_cache[item.full_key] = tiered
        return tiered

    async def progressive_search(
        self,
        query: MemoryQuery,
        *,
        l0_limit: int = 50,
        l1_limit: int = 10,
        l2_limit: int = 5,
    ) -> tuple[MemorySearchResult, ...]:
        """Progressive retrieval: broad L0 scan → L1 shortlist → L2 final selection."""
        # Stage 1: broad search via semantic store
        broad_query = MemoryQuery(
            text=query.text,
            scope=query.scope,
            scopes=query.scopes,
            min_confidence=query.min_confidence,
            max_age=query.max_age,
            scope_path=query.scope_path,
            limit=l0_limit,
        )
        candidates = await self._store.search(query=broad_query)

        if not candidates:
            return ()

        # Stage 2: narrow to l1_limit using the semantic store's ranking
        # (already scored by similarity + decay).
        shortlisted = candidates[:l1_limit]

        # Stage 3: return top l2_limit (the final selection).
        return tuple(shortlisted[:l2_limit])

    async def progressive_search_compacted(
        self,
        query: MemoryQuery,
        *,
        l0_limit: int = 50,
        l1_limit: int = 10,
        l2_limit: int = 5,
    ) -> tuple[CompactedMemory, ...]:
        """Tier-aware retrieval that actually reduces per-item cost.

        Unlike progressive_search (which returns full-content results and only
        narrows the COUNT), this returns each result at a tier matched to its
        rank, pulling pre-computed abstracts from the tier cache:
          - top l2_limit  → L2 (full content)
          - next l1_limit → L1 (overview)  — cheaper
          - rest (to l0)  → L0 (abstract)   — cheapest
        Lower-ranked items cost a fraction of their full tokens, so a planner
        sees breadth (many items) without paying full fidelity for all of them.
        """
        broad_query = MemoryQuery(
            text=query.text,
            scope=query.scope,
            scopes=query.scopes,
            min_confidence=query.min_confidence,
            max_age=query.max_age,
            scope_path=query.scope_path,
            limit=l0_limit,
        )
        candidates = await self._store.search(query=broad_query)
        if not candidates:
            return ()

        out: list[CompactedMemory] = []
        for rank, result in enumerate(candidates):
            tiered = self._tier_cache.get(result.item.full_key)
            tier = self._tier_for_rank(rank=rank, l2_limit=l2_limit, l1_limit=l1_limit)
            if tiered is not None:
                out.append(tiered.to_compacted(tier))
            else:
                # No cached tiers (item stored outside store_with_tiers): fall
                # back to full content so we never silently drop information.
                out.append(
                    CompactedMemory(
                        item=result.item,
                        level=CompactionLevel.FULL,
                        original_token_count=0,
                        compacted_token_count=0,
                    )
                )
        return tuple(out)

    @staticmethod
    def _tier_for_rank(*, rank: int, l2_limit: int, l1_limit: int) -> LoadingTier:
        """Map a result's rank to the tier it should load at."""
        if rank < l2_limit:
            return LoadingTier.L2
        if rank < l2_limit + l1_limit:
            return LoadingTier.L1
        return LoadingTier.L0

    def get_tiered(self, full_key: str) -> TieredMemoryItem | None:
        """Look up cached tiered item."""
        return self._tier_cache.get(full_key)
