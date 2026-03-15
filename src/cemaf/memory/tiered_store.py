"""Tier-aware memory store with progressive retrieval."""

from cemaf.memory.base import MemoryItem
from cemaf.memory.semantic import MemoryQuery, MemorySearchResult, SemanticMemoryStore
from cemaf.memory.tiered import TieredMemoryItem, TierGenerator


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
            limit=l0_limit,
        )
        candidates = await self._store.search(query=broad_query)

        if not candidates:
            return ()

        # Stage 2: narrow to l1_limit using L1 content relevance
        # For now, use the semantic store's ranking (already scored by similarity + decay)
        shortlisted = candidates[:l1_limit]

        # Stage 3: return top l2_limit with full content
        return tuple(shortlisted[:l2_limit])

    def get_tiered(self, full_key: str) -> TieredMemoryItem | None:
        """Look up cached tiered item."""
        return self._tier_cache.get(full_key)
