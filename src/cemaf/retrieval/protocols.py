"""
Retrieval protocols - Abstract interfaces for vector stores and embeddings.

Supports:
- Document storage with metadata
- Vector similarity search
- Embedding generation
- Filtering by metadata
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from cemaf.core.types import JSON
from cemaf.core.utils import utc_now


@dataclass(frozen=True)
class Document:
    """
    A document for vector storage.
    
    Contains content, embedding, and metadata.
    """

    id: str
    content: str
    embedding: tuple[float, ...] | None = None
    metadata: JSON = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    @property
    def has_embedding(self) -> bool:
        """Whether document has an embedding."""
        return self.embedding is not None and len(self.embedding) > 0

    def with_embedding(self, embedding: list[float] | tuple[float, ...]) -> Document:
        """Create copy with embedding."""
        return Document(
            id=self.id,
            content=self.content,
            embedding=tuple(embedding),
            metadata=self.metadata,
            created_at=self.created_at,
        )


@dataclass(frozen=True)
class SearchResult:
    """
    Result of a vector search.
    
    Includes document and similarity score.
    """

    document: Document
    score: float  # Similarity score (higher = more similar)
    rank: int = 0  # Position in results
    metadata: JSON = field(default_factory=dict)

    @property
    def id(self) -> str:
        """Document ID."""
        return self.document.id

    @property
    def content(self) -> str:
        """Document content."""
        return self.document.content


@runtime_checkable
class EmbeddingProvider(Protocol):
    """
    Protocol for embedding providers.
    
    Implement for different embedding models:
    - OpenAI text-embedding-3
    - Sentence Transformers
    - Cohere
    - Local models
    """

    @property
    def dimension(self) -> int:
        """Embedding dimension."""
        ...

    @property
    def model_name(self) -> str:
        """Model name/identifier."""
        ...

    async def embed(self, text: str) -> tuple[float, ...]:
        """
        Generate embedding for text.
        
        Args:
            text: Text to embed
        
        Returns:
            Embedding vector as tuple of floats
        """
        ...

    async def embed_batch(self, texts: list[str]) -> list[tuple[float, ...]]:
        """
        Generate embeddings for multiple texts.
        
        More efficient than calling embed() multiple times.
        
        Args:
            texts: List of texts to embed
        
        Returns:
            List of embedding vectors
        """
        ...


@runtime_checkable
class VectorStore(Protocol):
    """
    Protocol for vector stores.
    
    Implement for different backends:
    - Pinecone
    - Chroma
    - Qdrant
    - PGVector
    - Weaviate
    - FAISS (local)
    """

    async def add(self, document: Document) -> None:
        """
        Add a document to the store.
        
        Document must have an embedding.
        """
        ...

    async def add_batch(self, documents: list[Document]) -> None:
        """
        Add multiple documents.
        
        More efficient than calling add() multiple times.
        """
        ...

    async def get(self, document_id: str) -> Document | None:
        """
        Get a document by ID.
        
        Returns None if not found.
        """
        ...

    async def delete(self, document_id: str) -> bool:
        """
        Delete a document.
        
        Returns True if existed and was deleted.
        """
        ...

    async def search(
        self,
        query_embedding: tuple[float, ...],
        k: int = 10,
        filter: JSON | None = None,
    ) -> list[SearchResult]:
        """
        Search for similar documents.
        
        Args:
            query_embedding: Embedding to search for
            k: Number of results to return
            filter: Optional metadata filter
        
        Returns:
            List of SearchResults ordered by similarity
        """
        ...

    async def search_by_text(
        self,
        query_text: str,
        k: int = 10,
        filter: JSON | None = None,
    ) -> list[SearchResult]:
        """
        Search by text (embedding generated internally).
        
        Requires store to have an embedding provider configured.
        """
        ...

    async def count(self) -> int:
        """Get total number of documents."""
        ...

    async def clear(self) -> None:
        """Remove all documents."""
        ...

