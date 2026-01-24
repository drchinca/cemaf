"""
Tests for Semantic State Caching.
"""

from unittest.mock import AsyncMock

import pytest

from cemaf.cache.semantic import SemanticStateCache
from cemaf.context.context import Context
from cemaf.retrieval.protocols import Document, SearchResult


@pytest.fixture
def mock_vector_store():
    return AsyncMock()


@pytest.fixture
def mock_embedding_provider():
    mock = AsyncMock()
    mock.embed.return_value = (0.1, 0.2, 0.3)
    return mock


@pytest.mark.asyncio
async def test_semantic_cache_hit(mock_vector_store, mock_embedding_provider):
    """Test that semantic cache returns a hit when similarity is high."""
    cache = SemanticStateCache(
        vector_store=mock_vector_store, embedding_provider=mock_embedding_provider, threshold=0.95
    )

    ctx = Context(data={"key": "value"})

    # Mock a search result with high similarity
    mock_doc = Document(id="cached_state_1", content='{"key": "value"}')
    mock_vector_store.search.return_value = [SearchResult(document=mock_doc, score=0.98)]

    result_ctx = await cache.get(ctx)

    assert result_ctx is not None
    assert result_ctx.data == {"key": "value"}
    mock_embedding_provider.embed.assert_called_once()
    mock_vector_store.search.assert_called_once()


@pytest.mark.asyncio
async def test_semantic_cache_miss(mock_vector_store, mock_embedding_provider):
    """Test that semantic cache returns None when similarity is low."""
    cache = SemanticStateCache(
        vector_store=mock_vector_store, embedding_provider=mock_embedding_provider, threshold=0.95
    )

    ctx = Context(data={"key": "new_value"})

    # Mock a search result with low similarity
    mock_doc = Document(id="cached_state_1", content='{"key": "old_value"}')
    mock_vector_store.search.return_value = [SearchResult(document=mock_doc, score=0.80)]

    result_ctx = await cache.get(ctx)

    assert result_ctx is None


@pytest.mark.asyncio
async def test_semantic_cache_set(mock_vector_store, mock_embedding_provider):
    """Test storing a state in the semantic cache."""
    cache = SemanticStateCache(vector_store=mock_vector_store, embedding_provider=mock_embedding_provider)

    ctx = Context(data={"key": "to_cache"})

    await cache.set(ctx)

    mock_embedding_provider.embed.assert_called_once()
    mock_vector_store.add.assert_called_once()
    # Verify document content is the context data JSON
    added_doc = mock_vector_store.add.call_args[0][0]
    assert added_doc.content == '{"key": "to_cache"}'
