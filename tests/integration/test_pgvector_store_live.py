"""Opt-in production-boundary tests against a real local Postgres+pgvector.

Run with (a `pgvector/pgvector` Postgres reachable at CEMAF_PGVECTOR_DSN):
    CEMAF_RUN_PGVECTOR_TESTS=1 uv run pytest -q tests/integration/test_pgvector_store_live.py

This suite exists because the unit suite for PgVectorStore
(tests/unit/retrieval/test_pgvector_store.py) mocks every asyncpg call, and
tests/integration/test_postgres_memory_store.py drives a hand-written fake
pool — neither exercises asyncpg's real identifier quoting. That gap let a
real bug ship: `add_batch` passed a schema-qualified string
(f"{schema}.vector_documents") as `copy_records_to_table`'s `table_name`
positional, which asyncpg treats as one literal identifier (not
schema.table), raising `UndefinedTableError` against a real database every
time. Fixed by using the `schema_name=` kwarg instead. This suite proves the
whole store — schema/extension bootstrap, add, search, delete — against a
real connection so this class of bug can't silently reappear.
"""

from __future__ import annotations

import os
import uuid

import pytest

from cemaf.retrieval.pgvector_store import PgVectorStore
from cemaf.retrieval.protocols import Document

pytestmark = pytest.mark.skipif(
    os.getenv("CEMAF_RUN_PGVECTOR_TESTS") != "1",
    reason="set CEMAF_RUN_PGVECTOR_TESTS=1 with a real pgvector-enabled Postgres to execute",
)

_DSN = os.getenv("CEMAF_PGVECTOR_DSN", "postgresql://sipe:sipe@localhost:5432/sipe_vectors")


@pytest.fixture
def schema() -> str:
    """A unique schema per test run — a real database is a shared fixture, not a fresh one."""
    return f"cemaf_live_{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_add_search_delete_round_trip_against_real_postgres(schema: str) -> None:
    store = PgVectorStore(dsn=_DSN, dimension=3, schema=schema)
    try:
        doc = Document(
            id="doc-1",
            content="hello world",
            embedding=(0.1, 0.2, 0.3),
            metadata={"kind": "greeting"},
        )
        await store.add(doc)
        assert await store.count() == 1

        fetched = await store.get("doc-1")
        assert fetched is not None
        assert fetched.content == "hello world"

        results = await store.search(query_embedding=(0.1, 0.2, 0.3), k=1)
        assert len(results) == 1
        assert results[0].document.id == "doc-1"

        assert await store.delete("doc-1") is True
        assert await store.count() == 0
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_add_batch_writes_multiple_documents_via_copy(schema: str) -> None:
    """Direct regression test for the copy_records_to_table schema-name bug."""
    store = PgVectorStore(dsn=_DSN, dimension=3, schema=schema)
    try:
        docs = [
            Document(id=f"doc-{i}", content=f"content {i}", embedding=(0.1, 0.2, 0.3), metadata={})
            for i in range(5)
        ]
        await store.add_batch(docs)
        assert await store.count() == 5
    finally:
        await store.close()
