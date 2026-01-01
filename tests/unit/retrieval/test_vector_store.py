"""
Tests for vector store.
"""

import pytest

from cemaf.retrieval.memory_store import (
    InMemoryVectorStore,
    MockEmbeddingProvider,
    cosine_similarity,
)
from cemaf.retrieval.protocols import Document


class TestCosineSimiliarity:
    """Tests for cosine similarity function."""

    def test_identical_vectors(self):
        """Identical vectors have similarity 1."""
        v = (1.0, 2.0, 3.0)
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        """Orthogonal vectors have similarity 0."""
        v1 = (1.0, 0.0)
        v2 = (0.0, 1.0)
        assert cosine_similarity(v1, v2) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        """Opposite vectors have similarity -1."""
        v1 = (1.0, 0.0)
        v2 = (-1.0, 0.0)
        assert cosine_similarity(v1, v2) == pytest.approx(-1.0)

    def test_dimension_mismatch_raises(self):
        """Mismatched dimensions raise error."""
        with pytest.raises(ValueError):
            cosine_similarity((1.0, 2.0), (1.0, 2.0, 3.0))


class TestMockEmbeddingProvider:
    """Tests for MockEmbeddingProvider."""

    @pytest.mark.asyncio
    async def test_embed_returns_correct_dimension(self):
        """Embedding has correct dimension."""
        provider = MockEmbeddingProvider(dimension=128)

        embedding = await provider.embed("Test text")

        assert len(embedding) == 128

    @pytest.mark.asyncio
    async def test_embed_is_deterministic(self):
        """Same text produces same embedding."""
        provider = MockEmbeddingProvider()

        e1 = await provider.embed("Hello world")
        e2 = await provider.embed("Hello world")

        assert e1 == e2

    @pytest.mark.asyncio
    async def test_embed_batch(self):
        """Batch embedding works."""
        provider = MockEmbeddingProvider()

        embeddings = await provider.embed_batch(["Text 1", "Text 2", "Text 3"])

        assert len(embeddings) == 3

    def test_properties(self):
        """Provider has correct properties."""
        provider = MockEmbeddingProvider(dimension=256)

        assert provider.dimension == 256
        assert provider.model_name == "mock-embeddings"


class TestInMemoryVectorStore:
    """Tests for InMemoryVectorStore."""

    @pytest.fixture
    def store(self) -> InMemoryVectorStore:
        """Fresh vector store for each test."""
        provider = MockEmbeddingProvider(dimension=128)
        return InMemoryVectorStore(embedding_provider=provider)

    @pytest.mark.asyncio
    async def test_add_and_get(self, store: InMemoryVectorStore):
        """Can add and retrieve documents."""
        doc = Document(id="doc1", content="Test content")

        await store.add(doc)
        retrieved = await store.get("doc1")

        assert retrieved is not None
        assert retrieved.content == "Test content"
        assert retrieved.has_embedding  # Embedding was generated

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, store: InMemoryVectorStore):
        """Getting nonexistent returns None."""

        result = await store.get("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_delete(self, store: InMemoryVectorStore):
        """Can delete documents."""
        await store.add(Document(id="doc1", content="Test"))

        deleted = await store.delete("doc1")

        assert deleted is True
        assert await store.get("doc1") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, store: InMemoryVectorStore):
        """Deleting nonexistent returns False."""

        deleted = await store.delete("nonexistent")

        assert deleted is False

    @pytest.mark.asyncio
    async def test_search_returns_similar(self, store: InMemoryVectorStore):
        """Search returns similar documents."""

        await store.add(Document(id="1", content="The cat sat on the mat"))
        await store.add(Document(id="2", content="Dogs are great pets"))
        await store.add(Document(id="3", content="The kitten played with yarn"))

        results = await store.search_by_text("cat", k=2)

        assert len(results) <= 2
        # Results should be ordered by similarity
        if len(results) >= 2:
            assert results[0].score >= results[1].score

    @pytest.mark.asyncio
    async def test_search_with_filter(self, store: InMemoryVectorStore):
        """Search can filter by metadata."""

        await store.add(Document(id="1", content="Doc 1", metadata={"type": "article"}))
        await store.add(Document(id="2", content="Doc 2", metadata={"type": "book"}))
        await store.add(Document(id="3", content="Doc 3", metadata={"type": "article"}))

        results = await store.search_by_text("Doc", k=10, filter={"type": "article"})

        assert all(r.document.metadata["type"] == "article" for r in results)

    @pytest.mark.asyncio
    async def test_count(self, store: InMemoryVectorStore):
        """Count returns document count."""

        await store.add(Document(id="1", content="One"))
        await store.add(Document(id="2", content="Two"))

        count = await store.count()

        assert count == 2

    @pytest.mark.asyncio
    async def test_clear(self, store: InMemoryVectorStore):
        """Clear removes all documents."""

        await store.add(Document(id="1", content="Test"))
        await store.clear()

        assert await store.count() == 0

    @pytest.mark.asyncio
    async def test_add_batch(self, store: InMemoryVectorStore):
        """Can add multiple documents at once."""

        docs = [
            Document(id="1", content="First"),
            Document(id="2", content="Second"),
            Document(id="3", content="Third"),
        ]

        await store.add_batch(docs)

        assert await store.count() == 3
