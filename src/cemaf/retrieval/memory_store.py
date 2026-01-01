"""
In-memory vector store for testing and development.

Uses cosine similarity for search.
"""

import math

from cemaf.core.types import JSON
from cemaf.retrieval.protocols import (
    Document,
    EmbeddingProvider,
    SearchResult,
)


def cosine_similarity(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """
    Calculate cosine similarity between two vectors.

    Returns value between -1 and 1.
    """
    if len(a) != len(b):
        raise ValueError(f"Vector dimensions don't match: {len(a)} vs {len(b)}")

    dot_product = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)


class MockEmbeddingProvider:
    """
    Mock embedding provider for testing.

    Generates deterministic embeddings based on text content.
    """

    def __init__(self, dimension: int = 384) -> None:
        self._dimension = dimension
        self._model_name = "mock-embeddings"

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    async def embed(self, text: str) -> tuple[float, ...]:
        """Generate deterministic embedding from text."""
        # Simple hash-based embedding for testing
        # NOT suitable for real semantic search
        embedding = [0.0] * self._dimension

        for i, char in enumerate(text.lower()):
            idx = (ord(char) + i) % self._dimension
            embedding[idx] += 0.1

        # Normalize
        norm = math.sqrt(sum(x * x for x in embedding)) or 1.0
        return tuple(x / norm for x in embedding)

    async def embed_batch(self, texts: list[str]) -> list[tuple[float, ...]]:
        """Generate embeddings for multiple texts."""
        return [await self.embed(text) for text in texts]


class InMemoryVectorStore:
    """
    In-memory vector store for testing.

    Stores documents in a dict, uses brute-force search.
    NOT suitable for production with large datasets.

    Usage:
        store = InMemoryVectorStore()
        await store.add(Document(id="1", content="Hello", embedding=(...,)))
        results = await store.search(query_embedding, k=5)
    """

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self._documents: dict[str, Document] = {}
        self._embedding_provider = embedding_provider

    async def add(self, document: Document) -> None:
        """Add a document."""
        if not document.has_embedding:
            # Generate embedding if not provided
            embedding = await self._embedding_provider.embed(document.content)
            document = document.with_embedding(embedding)

        self._documents[document.id] = document

    async def add_batch(self, documents: list[Document]) -> None:
        """Add multiple documents."""
        for doc in documents:
            await self.add(doc)

    async def get(self, document_id: str) -> Document | None:
        """Get a document by ID."""
        return self._documents.get(document_id)

    async def delete(self, document_id: str) -> bool:
        """Delete a document."""
        if document_id in self._documents:
            del self._documents[document_id]
            return True
        return False

    async def search(
        self,
        query_embedding: tuple[float, ...],
        k: int = 10,
        filter: JSON | None = None,
    ) -> list[SearchResult]:
        """Search for similar documents."""
        results: list[tuple[float, Document]] = []

        for doc in self._documents.values():
            # Apply filter
            if filter and not self._matches_filter(doc, filter):
                continue

            if not doc.has_embedding:
                continue

            score = cosine_similarity(query_embedding, doc.embedding)  # type: ignore
            results.append((score, doc))

        # Sort by score descending
        results.sort(key=lambda x: x[0], reverse=True)

        # Return top k
        return [SearchResult(document=doc, score=score, rank=i) for i, (score, doc) in enumerate(results[:k])]

    async def search_by_text(
        self,
        query_text: str,
        k: int = 10,
        filter: JSON | None = None,
    ) -> list[SearchResult]:
        """Search by text."""
        query_embedding = await self._embedding_provider.embed(query_text)
        return await self.search(query_embedding, k=k, filter=filter)

    async def count(self) -> int:
        """Get document count."""
        return len(self._documents)

    async def clear(self) -> None:
        """Clear all documents."""
        self._documents.clear()

    def _matches_filter(self, doc: Document, filter: JSON) -> bool:
        """Check if document matches filter."""
        for key, value in filter.items():
            doc_value = doc.metadata.get(key)
            if doc_value != value:
                return False
        return True
