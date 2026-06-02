"""
Retrieval module - Vector search and hybrid retrieval.

Provides:
- VectorStore protocol for pluggable backends
- EmbeddingProvider protocol for embedding models
- HybridRetriever combining vector + keyword search
- InMemoryVectorStore for testing

Configuration:
    See cemaf.config.protocols.RetrievalSettings for available settings.
    Environment variables: CEMAF_RETRIEVAL_*

Usage:
    # Recommended: Use factory with configuration
    from cemaf.retrieval import create_vector_store_from_config
    store = create_vector_store_from_config()

    # Direct instantiation
    from cemaf.retrieval import InMemoryVectorStore
    store = InMemoryVectorStore(embedding_provider)
"""

from cemaf.retrieval.embedding_providers import HashEmbeddingProvider
from cemaf.retrieval.factories import (
    create_embedding_provider_from_config,
    create_in_memory_vector_store,
    create_vector_store_from_config,
)
from cemaf.retrieval.huggingface_embeddings import HuggingFaceEmbeddingProvider
from cemaf.retrieval.hybrid import HybridRetriever, RetrievalConfig
from cemaf.retrieval.memory_store import InMemoryVectorStore
from cemaf.retrieval.openai_embeddings import OpenAIEmbeddingProvider
from cemaf.retrieval.protocols import (
    Document,
    EmbeddingProvider,
    SearchResult,
    VectorStore,
)

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
    "HashEmbeddingProvider",
    "HuggingFaceEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    # Factories
    "create_embedding_provider_from_config",
    "create_in_memory_vector_store",
    "create_vector_store_from_config",
]
