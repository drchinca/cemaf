"""Tests for retrieval factory functions."""

from pathlib import Path

from cemaf.retrieval.factories import create_embedding_provider, create_vector_store
from cemaf.retrieval.sqlite_vector_store import SqliteVectorStore


def test_create_embedding_provider_hash_uses_dimension() -> None:
    provider = create_embedding_provider(provider="hash", dimension=512)

    assert provider.dimension == 512


def test_create_vector_store_sqlite_uses_explicit_db_path(tmp_path: Path) -> None:
    provider = create_embedding_provider(provider="hash", dimension=128)

    store = create_vector_store(
        backend="sqlite",
        embedding_provider=provider,
        dimension=128,
        db_path=str(tmp_path / "vectors.db"),
    )

    assert isinstance(store, SqliteVectorStore)
