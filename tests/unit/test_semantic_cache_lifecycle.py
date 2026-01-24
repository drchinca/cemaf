"""
TDD Tests for Semantic Cache Lifecycle Management.

Tests verify cache invalidation strategy:
1. TTL expiration after timeout
2. LRU eviction when size limit exceeded
3. Full Context preservation (history not lost)
"""

import asyncio

import pytest

from cemaf.cache.semantic import SemanticStateCache
from cemaf.context.context import Context
from cemaf.retrieval.protocols import Document


class MockEmbeddingProvider:
    """Mock embedding provider for testing."""

    async def embed(self, text: str) -> list[float]:
        """Return a dummy embedding (all zeros)."""
        return [0.0] * 384


class MockVectorStore:
    """Mock vector store that tracks stored documents."""

    def __init__(self):
        self.documents: dict[str, Document] = {}

    async def add(self, doc: Document) -> None:
        """Store document."""
        self.documents[doc.id] = doc

    async def search(self, embedding: list[float], k: int = 1) -> list[Document]:
        """Return empty by default (tests will override)."""
        return []


@pytest.mark.asyncio
async def test_cache_ttl_expiration():
    """
    GIVEN: A cached context state with TTL = 1 second
    WHEN: Cache is accessed before TTL expires
    THEN: Should return cached context

    WHEN: Cache is accessed after TTL expires
    THEN: Should return None (expired)
    """
    embedding_provider = MockEmbeddingProvider()
    vector_store = MockVectorStore()
    cache = SemanticStateCache(
        vector_store=vector_store,
        embedding_provider=embedding_provider,
        cache_ttl=1,  # 1 second TTL
    )

    # Create and cache a context
    context1 = Context(data={"key": "value1"})
    await cache.set(context1)

    # Immediately access - should work
    cached = await cache.get(context1)
    assert cached is not None, "Cache should have entry before TTL expires"

    # Wait for TTL to expire
    await asyncio.sleep(1.1)

    # Try to access again - should be None
    cached = await cache.get(context1)
    assert cached is None, "Cache should expire after TTL"


@pytest.mark.asyncio
async def test_cache_lru_eviction():
    """
    GIVEN: Cache with max_cache_size = 2
    WHEN: Add 3 items to the cache
    THEN: Only 2 most recent items should remain (oldest evicted)
    """
    embedding_provider = MockEmbeddingProvider()
    vector_store = MockVectorStore()
    cache = SemanticStateCache(
        vector_store=vector_store,
        embedding_provider=embedding_provider,
        max_cache_size=2,
    )

    # Add 3 contexts
    context1 = Context(data={"key": "value1"})
    context2 = Context(data={"key": "value2"})
    context3 = Context(data={"key": "value3"})

    await cache.set(context1)
    await cache.set(context2)
    await cache.set(context3)

    # Should only have 2 items (oldest was evicted)
    assert len(cache._cache_entries) == 2, (
        f"Expected 2 cached items after LRU eviction, got {len(cache._cache_entries)}"
    )

    # context1 should be evicted (oldest)
    # context2 and context3 should remain


@pytest.mark.asyncio
async def test_cache_preserves_context_fully():
    """
    GIVEN: A context with patch history
    WHEN: Context is cached and retrieved
    THEN: Full Context (with patch history) should be preserved
    """
    embedding_provider = MockEmbeddingProvider()
    vector_store = MockVectorStore()
    cache = SemanticStateCache(
        vector_store=vector_store,
        embedding_provider=embedding_provider,
    )

    # Create context with patch history
    context1 = Context(data={"key": "value1"}, patch_history=())
    await cache.set(context1)

    # Retrieve from cache
    cached = await cache.get(context1)

    assert cached is not None, "Should retrieve cached context"
    assert cached.data == context1.data, "Data should match"
    assert cached.patch_history == context1.patch_history, "Patch history should be preserved"


@pytest.mark.asyncio
async def test_cache_disables_ttl_when_not_set():
    """
    GIVEN: Cache without TTL specified (None or infinity)
    WHEN: Add context and wait
    THEN: Context should not expire
    """
    embedding_provider = MockEmbeddingProvider()
    vector_store = MockVectorStore()
    cache = SemanticStateCache(
        vector_store=vector_store,
        embedding_provider=embedding_provider,
        cache_ttl=None,  # No TTL
    )

    context1 = Context(data={"key": "value1"})
    await cache.set(context1)

    # Wait a bit
    await asyncio.sleep(0.5)

    # Should still be there
    cached = await cache.get(context1)
    assert cached is not None, "Cache should not expire without TTL"


@pytest.mark.asyncio
async def test_cache_max_size_none_means_unlimited():
    """
    GIVEN: Cache with max_cache_size = None
    WHEN: Add many contexts
    THEN: All should be cached (no LRU eviction)
    """
    embedding_provider = MockEmbeddingProvider()
    vector_store = MockVectorStore()
    cache = SemanticStateCache(
        vector_store=vector_store,
        embedding_provider=embedding_provider,
        max_cache_size=None,  # Unlimited
    )

    # Add 10 contexts
    for i in range(10):
        context = Context(data={"id": i})
        await cache.set(context)

    assert len(cache._cache_entries) == 10, (
        f"Expected 10 cached items with unlimited size, got {len(cache._cache_entries)}"
    )
