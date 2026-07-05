"""Factory functions for retrieval components."""

import os
from typing import TYPE_CHECKING, Any

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.core.defaults import DEFAULT_FREE_EMBEDDING_PROVIDER
from cemaf.core.provider_registry import ProviderRegistry
from cemaf.retrieval.embedding_providers import HashEmbeddingProvider
from cemaf.retrieval.huggingface_embeddings import (
    DEFAULT_HF_EMBEDDING_DIMENSION,
    DEFAULT_HF_EMBEDDING_MODEL,
    HuggingFaceEmbeddingProvider,
)
from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider
from cemaf.retrieval.openai_embeddings import OpenAIEmbeddingProvider
from cemaf.retrieval.protocols import EmbeddingProvider, VectorStore
from cemaf.retrieval.sqlite_vector_store import SqliteVectorStore

if TYPE_CHECKING:
    from cemaf.retrieval.pgvector_store import PgVectorStore

# Global vector store registry — extend with your own backends
vector_store_registry: ProviderRegistry[VectorStore] = ProviderRegistry(name="vector_store")
embedding_provider_registry: ProviderRegistry[EmbeddingProvider] = ProviderRegistry(name="embedding_provider")


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


def _create_pgvector_store(**kwargs: Any) -> PgVectorStore:
    """Registry-compatible factory for pgvector store."""
    return create_pg_vector_store(
        dsn=kwargs.get("dsn"),
        dimension=kwargs.get("dimension", 3072),
        tenant_id=kwargs.get("tenant_id", "default"),
        embedding_provider=kwargs.get("embedding_provider"),
    )


def _create_sqlite_vector_store(**kwargs: Any) -> SqliteVectorStore:
    """Registry-compatible factory for a SQLite vector store."""
    provider = kwargs.get("embedding_provider")
    if provider is None:
        provider = MockEmbeddingProvider(dimension=int(kwargs.get("dimension", 384)))
    return SqliteVectorStore(
        db_path=str(kwargs.get("db_path") or os.getenv("CEMAF_RETRIEVAL_SQLITE_PATH", "cemaf_memory.db")),
        embedding_provider=provider,
    )


def _create_hash_embedding_provider(**kwargs: Any) -> EmbeddingProvider:
    return HashEmbeddingProvider(dimension=int(kwargs.get("dimension", 384)))


def _create_openai_embedding_provider(**kwargs: Any) -> EmbeddingProvider:
    api_key = str(kwargs.get("api_key") or os.getenv("OPENAI_API_KEY", ""))
    if not api_key:
        raise ValueError("api_key required for OpenAI embeddings (or set OPENAI_API_KEY)")
    return OpenAIEmbeddingProvider(
        api_key=api_key,
        model=str(kwargs.get("model", "text-embedding-3-small")),
        dimension=int(kwargs.get("dimension", 1536)),
    )


def _create_huggingface_embedding_provider(**kwargs: Any) -> EmbeddingProvider:
    model = str(kwargs.get("model", DEFAULT_HF_EMBEDDING_MODEL))
    dimension = int(kwargs.get("dimension", DEFAULT_HF_EMBEDDING_DIMENSION))

    if model == "text-embedding-3-small":
        model = DEFAULT_HF_EMBEDDING_MODEL
    if dimension == 1536 and model == DEFAULT_HF_EMBEDDING_MODEL:
        dimension = DEFAULT_HF_EMBEDDING_DIMENSION

    return HuggingFaceEmbeddingProvider(
        api_key=str(kwargs.get("api_key", "")),
        model=model,
        dimension=dimension,
        provider=str(kwargs.get("provider", "hf-inference")),
        timeout_seconds=float(kwargs.get("timeout_seconds", 60.0)),
    )


# Register built-in backends
vector_store_registry.register(backend="memory", factory=_create_memory_vector_store)
vector_store_registry.register(backend="sqlite", factory=_create_sqlite_vector_store)
vector_store_registry.register(backend="pgvector", factory=_create_pgvector_store)
embedding_provider_registry.register(backend="hash", factory=_create_hash_embedding_provider)
embedding_provider_registry.register(backend="mock", factory=_create_hash_embedding_provider)
embedding_provider_registry.register(backend="openai", factory=_create_openai_embedding_provider)
embedding_provider_registry.register(backend="huggingface", factory=_create_huggingface_embedding_provider)
embedding_provider_registry.register(
    backend="sentence-transformers",
    factory=_create_huggingface_embedding_provider,
)


def create_vector_store(
    backend: str = "memory",
    *,
    embedding_provider: EmbeddingProvider | None = None,
    dimension: int = 384,
    db_path: str | None = None,
    dsn: str | None = None,
    tenant_id: str = "default",
) -> VectorStore:
    """Create a vector store without routing through environment-backed settings."""
    return vector_store_registry.create(
        backend=backend,
        embedding_provider=embedding_provider,
        dimension=dimension,
        db_path=db_path,
        dsn=dsn,
        tenant_id=tenant_id,
    )


def create_embedding_provider(
    provider: str = DEFAULT_FREE_EMBEDDING_PROVIDER,
    *,
    model: str | None = None,
    dimension: int = 384,
    api_key: str | None = None,
    inference_provider: str = "hf-inference",
    timeout_seconds: float = 60.0,
) -> EmbeddingProvider:
    """Create an embedding provider without routing through environment-backed settings."""
    kwargs: dict[str, Any] = {
        "dimension": dimension,
        "api_key": api_key or "",
        "provider": inference_provider,
        "timeout_seconds": timeout_seconds,
    }
    if model is not None:
        kwargs["model"] = model
    return embedding_provider_registry.create(backend=provider, **kwargs)


def create_vector_store_from_config(
    backend: str | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    settings: Settings | None = None,
) -> VectorStore:
    """Create a vector store from configuration."""
    cfg = settings or load_settings_from_env_sync()
    backend = backend or os.getenv("CEMAF_VECTOR_STORE_BACKEND") or cfg.retrieval.vector_store_backend
    dimension = int(os.getenv("CEMAF_EMBEDDING_DIMENSION", str(cfg.retrieval.embedding_dimension)))

    return create_vector_store(
        backend=backend,
        embedding_provider=embedding_provider,
        dimension=dimension,
        db_path=os.getenv("CEMAF_RETRIEVAL_SQLITE_PATH", "cemaf_memory.db"),
        dsn=os.getenv("CEMAF_POSTGRES_DSN"),
    )


def create_embedding_provider_from_config(
    provider: str | None = None,
    settings: Settings | None = None,
) -> EmbeddingProvider:
    """Create an embedding provider from retrieval settings."""

    cfg = settings or load_settings_from_env_sync()
    provider_name = provider or os.getenv("CEMAF_EMBEDDING_PROVIDER") or cfg.retrieval.embedding_provider
    model = os.getenv("CEMAF_EMBEDDING_MODEL", cfg.retrieval.embedding_model)
    dimension = int(os.getenv("CEMAF_EMBEDDING_DIMENSION", str(cfg.retrieval.embedding_dimension)))
    return create_embedding_provider(
        provider=provider_name,
        model=model or None,
        dimension=dimension,
    )


def create_pg_vector_store(
    *,
    dsn: str | None = None,
    dimension: int = 3072,
    tenant_id: str = "default",
    embedding_provider: EmbeddingProvider | None = None,
) -> PgVectorStore:
    """Create a PgVectorStore, reading DSN from env when dsn is None.

    Pass embedding_provider when callers need search_by_text(); callers with
    precomputed vectors can still use search() directly without one.
    Reads CEMAF_POSTGRES_DSN when dsn is None.
    """
    resolved_dsn: str = dsn or os.getenv("CEMAF_POSTGRES_DSN") or "postgresql://localhost/cemaf"
    from cemaf.retrieval.pgvector_store import PgVectorStore

    return PgVectorStore(
        dsn=resolved_dsn,
        dimension=dimension,
        tenant_id=tenant_id,
        embedding_provider=embedding_provider,
    )
