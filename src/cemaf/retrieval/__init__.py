"""
Retrieval module - Vector search and hybrid retrieval.

Provides:
- VectorStore protocol for pluggable backends
- EmbeddingProvider protocol for embedding models
- HybridRetriever combining vector + keyword search
- InMemoryVectorStore for testing
"""

from cemaf.retrieval.protocols import (
    VectorStore,
    EmbeddingProvider,
    SearchResult,
    Document,
)
from cemaf.retrieval.hybrid import HybridRetriever, RetrievalConfig
from cemaf.retrieval.memory_store import InMemoryVectorStore

__all__ = [
    # Protocols
    "VectorStore",
    "EmbeddingProvider",
    # Data types
    "SearchResult",
    "Document",
    # Implementations
    "HybridRetriever",
    "RetrievalConfig",
    "InMemoryVectorStore",
]

