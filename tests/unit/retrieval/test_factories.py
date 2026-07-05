"""Tests for retrieval factory functions."""

from pathlib import Path
from typing import get_args

import pytest

from cemaf.config.protocols import RetrievalSettings
from cemaf.core.defaults import (
    DEFAULT_FREE_EMBEDDING_DIMENSION,
    DEFAULT_FREE_EMBEDDING_MODEL,
    DEFAULT_FREE_EMBEDDING_PROVIDER,
)
from cemaf.retrieval.embedding_providers import HashEmbeddingProvider
from cemaf.retrieval.factories import (
    create_embedding_provider,
    create_embedding_provider_from_config,
    create_pg_vector_store,
    create_vector_store,
    create_vector_store_from_config,
    embedding_provider_registry,
    vector_store_registry,
)
from cemaf.retrieval.pgvector_store import PgVectorStore
from cemaf.retrieval.sqlite_vector_store import SqliteVectorStore


def test_configured_vector_store_backends_are_registered() -> None:
    backend_annotation = RetrievalSettings.model_fields["vector_store_backend"].annotation
    configured = set(get_args(backend_annotation))
    registered = set(vector_store_registry.list_backends())

    assert configured == registered


def test_configured_embedding_providers_are_registered() -> None:
    provider_annotation = RetrievalSettings.model_fields["embedding_provider"].annotation
    configured = set(get_args(provider_annotation))
    registered = set(embedding_provider_registry.list_backends())

    assert configured == registered


def test_create_embedding_provider_hash_uses_dimension() -> None:
    provider = create_embedding_provider(provider="hash", dimension=512)

    assert provider.dimension == 512


def test_create_embedding_provider_default_is_free_offline() -> None:
    provider = create_embedding_provider()

    assert isinstance(provider, HashEmbeddingProvider)
    assert provider.model_name == DEFAULT_FREE_EMBEDDING_MODEL
    assert provider.dimension == DEFAULT_FREE_EMBEDDING_DIMENSION
    assert DEFAULT_FREE_EMBEDDING_PROVIDER == "hash"


def test_create_embedding_provider_rejects_non_positive_dimension() -> None:
    with pytest.raises(ValueError, match="dimension must be positive, got 0"):
        create_embedding_provider(provider="hash", dimension=0)


def test_create_vector_store_sqlite_uses_explicit_db_path(tmp_path: Path) -> None:
    provider = create_embedding_provider(provider="hash", dimension=128)

    store = create_vector_store(
        backend="sqlite",
        embedding_provider=provider,
        dimension=128,
        db_path=str(tmp_path / "vectors.db"),
    )

    assert isinstance(store, SqliteVectorStore)


def test_create_pg_vector_store_preserves_embedding_provider() -> None:
    provider = create_embedding_provider(provider="hash", dimension=128)

    store = create_pg_vector_store(
        dsn="postgresql://localhost/cemaf",
        dimension=128,
        embedding_provider=provider,
    )

    assert isinstance(store, PgVectorStore)
    assert store._embedding_provider is provider


def test_create_vector_store_from_config_reads_documented_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("CEMAF_VECTOR_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("CEMAF_RETRIEVAL_SQLITE_PATH", str(tmp_path / "env-vectors.db"))
    monkeypatch.setenv("CEMAF_EMBEDDING_DIMENSION", "128")

    store = create_vector_store_from_config()

    assert isinstance(store, SqliteVectorStore)


def test_create_embedding_provider_from_config_reads_documented_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CEMAF_EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("CEMAF_EMBEDDING_DIMENSION", "256")

    provider = create_embedding_provider_from_config()

    assert provider.dimension == 256


def test_create_embedding_provider_from_default_config_is_free_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in ("CEMAF_EMBEDDING_PROVIDER", "CEMAF_EMBEDDING_MODEL", "CEMAF_EMBEDDING_DIMENSION"):
        monkeypatch.delenv(key, raising=False)

    provider = create_embedding_provider_from_config()

    assert isinstance(provider, HashEmbeddingProvider)
    assert provider.model_name == DEFAULT_FREE_EMBEDDING_MODEL
    assert provider.dimension == DEFAULT_FREE_EMBEDDING_DIMENSION
