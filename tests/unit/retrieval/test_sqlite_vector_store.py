"""Tests for the SQLite-backed vector store."""

from pathlib import Path

import pytest

from cemaf.retrieval.embedding_providers import HashEmbeddingProvider
from cemaf.retrieval.protocols import Document
from cemaf.retrieval.sqlite_vector_store import SqliteVectorStore


@pytest.fixture
def provider() -> HashEmbeddingProvider:
    return HashEmbeddingProvider(dimension=32)


@pytest.mark.asyncio
async def test_sqlite_vector_store_persists_across_instances(
    tmp_path: Path, provider: HashEmbeddingProvider
) -> None:
    db_path = tmp_path / "vectors.db"
    store = SqliteVectorStore(db_path=str(db_path), embedding_provider=provider)
    await store.add(
        Document(
            id="doc-1",
            content="brand consistency and audience trust",
            metadata={"scope": "project", "kind": "research"},
        )
    )
    await store.close()

    reopened = SqliteVectorStore(db_path=str(db_path), embedding_provider=provider)
    retrieved = await reopened.get("doc-1")
    results = await reopened.search_by_text("audience trust", k=5)

    assert retrieved is not None
    assert retrieved.content == "brand consistency and audience trust"
    assert any(result.document.id == "doc-1" for result in results)
    await reopened.close()


@pytest.mark.asyncio
async def test_sqlite_vector_store_search_supports_metadata_filters(
    tmp_path: Path, provider: HashEmbeddingProvider
) -> None:
    store = SqliteVectorStore(db_path=str(tmp_path / "filters.db"), embedding_provider=provider)
    await store.add_batch(
        [
            Document(id="a", content="content strategy", metadata={"scope": "project"}),
            Document(id="b", content="system level knowledge", metadata={"scope": "global"}),
        ]
    )

    results = await store.search_by_text(
        "strategy",
        k=5,
        filter={"scope": "project"},
    )

    assert [result.document.id for result in results] == ["a"]
    await store.close()


@pytest.mark.asyncio
async def test_sqlite_vector_store_delete_removes_document(
    tmp_path: Path, provider: HashEmbeddingProvider
) -> None:
    store = SqliteVectorStore(db_path=str(tmp_path / "delete.db"), embedding_provider=provider)
    await store.add(Document(id="doc-1", content="delete me"))

    deleted = await store.delete("doc-1")
    missing = await store.get("doc-1")

    assert deleted is True
    assert missing is None
    assert await store.count() == 0
    await store.close()
