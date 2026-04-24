"""Factory functions for retrieval components."""

import os
from typing import TYPE_CHECKING, Any

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.core.provider_registry import ProviderRegistry
from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider
from cemaf.retrieval.protocols import EmbeddingProvider, VectorStore

if TYPE_CHECKING:
    from cemaf.retrieval.pgvector_store import PgVectorStore

# Global vector store registry — extend with your own backends
vector_store_registry: ProviderRegistry[VectorStore] = ProviderRegistry(name="vector_store")


def create_in_memory_vector_store(
    embedding_provider: EmbeddingProvider | None = None,
    dimension: int = 384,
) -> InMemoryVectorStore:
    """Factory for InMemoryVectorStore with sensible defaults."""
    provider = embedding_provider or MockEmbeddingProvider(dimension=dimension)
    return InMemoryVectorStore(provider)


def _create_memory_vector_store(**kwargs: Any) -> InMemoryVectorStore:
    """Registry-compatible factory for in-memory vector store."""
    return create_in_memory_vector_store(
        embedding_provider=kwargs.get("embedding_provider"),
        dimension=kwargs.get("dimension", 384),
    )


def _create_pgvector_store(**kwargs: Any) -> "PgVectorStore":
    """Registry-compatible factory for pgvector store."""
    return create_pg_vector_store(
        dsn=kwargs.get("dsn"),
        dimension=kwargs.get("dimension", 3072),
        tenant_id=kwargs.get("tenant_id", "default"),
        embedding_provider=kwargs.get("embedding_provider"),
    )


# Register built-in backends
vector_store_registry.register(backend="memory", factory=_create_memory_vector_store)
vector_store_registry.register(backend="pgvector", factory=_create_pgvector_store)


def create_vector_store_from_config(
    backend: str | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    settings: Settings | None = None,
) -> VectorStore:
    """Create a vector store from configuration."""
    cfg = settings or load_settings_from_env_sync()
    backend = backend or cfg.retrieval.vector_store_backend

    return vector_store_registry.create(
        backend=backend,
        embedding_provider=embedding_provider,
        dimension=cfg.retrieval.embedding_dimension,
    )


def create_pg_vector_store(
    *,
    dsn: str | None = None,
    dimension: int = 3072,
    tenant_id: str = "default",
    embedding_provider: EmbeddingProvider | None = None,
) -> "PgVectorStore":
    """Create a PgVectorStore, reading DSN from env when dsn is None.

    embedding_provider is accepted for API compatibility but not used internally —
    PgVectorStore requires callers to embed externally and pass vectors to search().
    Reads CEMAF_POSTGRES_DSN when dsn is None.
    """
    resolved_dsn = dsn or os.getenv("CEMAF_POSTGRES_DSN", "postgresql://localhost/cemaf")
    from cemaf.retrieval.pgvector_store import PgVectorStore

    return PgVectorStore(dsn=resolved_dsn, dimension=dimension, tenant_id=tenant_id)
