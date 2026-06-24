"""SQLite-backed vector store for local persistent semantic retrieval."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from threading import Lock

import aiosqlite

from cemaf.core.types import JSON
from cemaf.retrieval.protocols import Document, EmbeddingProvider, SearchResult

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS vector_documents (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    embedding_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

_DB_LOCKS_GUARD = Lock()
_DB_LOCKS: dict[str, Lock] = {}


def _db_lock_for(path: str) -> Lock:
    """Return a process-local lock for a canonical SQLite database path."""
    key = str(Path(path).expanduser().resolve())
    with _DB_LOCKS_GUARD:
        lock = _DB_LOCKS.get(key)
        if lock is None:
            lock = Lock()
            _DB_LOCKS[key] = lock
        return lock


@asynccontextmanager
async def _locked_db(path: str) -> AsyncIterator[None]:
    """Acquire the process-local db lock without blocking the event loop."""
    lock = _db_lock_for(path)
    if not lock.acquire(blocking=False):
        await asyncio.to_thread(lock.acquire)
    try:
        yield
    finally:
        lock.release()


def _cosine_similarity(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Calculate cosine similarity between two vectors."""
    if len(a) != len(b):
        raise ValueError(f"Vector dimensions don't match: {len(a)} vs {len(b)}")

    dot_product = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)


def _matches_operator(*, actual: object, expression: dict[str, object]) -> bool:
    """Evaluate a {operator: operand} expression against a metadata value."""
    for operator, operand in expression.items():
        if operator == "$in":
            if not isinstance(operand, (list, tuple, set)):
                raise ValueError(f"$in operand must be iterable, got {type(operand).__name__}")
            if actual not in operand:
                return False
        elif operator == "$nin":
            if not isinstance(operand, (list, tuple, set)):
                raise ValueError(f"$nin operand must be iterable, got {type(operand).__name__}")
            if actual in operand:
                return False
        elif operator == "$ne":
            if actual == operand:
                return False
        elif operator == "$eq":
            if actual != operand:
                return False
        else:
            raise ValueError(f"Unsupported filter operator: {operator}")
    return True


def _matches_filter(doc: Document, filter: JSON | None) -> bool:
    """Check if document metadata satisfies filter expressions."""
    if not filter:
        return True
    for key, expected in filter.items():
        actual = doc.metadata.get(key)
        if isinstance(expected, dict):
            if not _matches_operator(actual=actual, expression=expected):
                return False
        elif actual != expected:
            return False
    return True


def _row_to_document(row: aiosqlite.Row) -> Document:
    """Deserialize a database row into a Document."""
    return Document(
        id=row[0],
        content=row[1],
        embedding=tuple(json.loads(row[2])),
        metadata=json.loads(row[3]),
        created_at=datetime.fromisoformat(row[4]),
    )


class SqliteVectorStore:
    """Persistent vector store backed by SQLite via aiosqlite."""

    def __init__(
        self,
        *,
        db_path: str = "cemaf_memory.db",
        embedding_provider: EmbeddingProvider,
        busy_timeout_ms: int = 5000,
        journal_mode: str = "WAL",
    ) -> None:
        self._db_path = db_path
        self._embedding_provider = embedding_provider
        self._busy_timeout_ms = busy_timeout_ms
        self._journal_mode = journal_mode
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def _connection(self) -> aiosqlite.Connection:
        """Return the lazy-initialized, pragma-tuned connection."""
        if self._conn is not None:
            return self._conn
        async with _locked_db(self._db_path):
            if self._conn is not None:
                return self._conn
            async with self._lock:
                if self._conn is not None:
                    return self._conn
                conn = await aiosqlite.connect(
                    self._db_path,
                    timeout=self._busy_timeout_ms / 1000,
                )
                conn.row_factory = aiosqlite.Row
                await conn.execute(f"PRAGMA journal_mode={self._journal_mode}")
                await conn.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
                await conn.execute("PRAGMA synchronous=NORMAL")
                await conn.execute(_CREATE_TABLE)
                await conn.commit()
                self._conn = conn
        return self._conn

    async def close(self) -> None:
        """Close the underlying connection. Idempotent."""
        async with self._lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None

    async def add(self, document: Document) -> None:
        """Add or replace a document."""
        if not document.has_embedding:
            document = document.with_embedding(await self._embedding_provider.embed(document.content))

        conn = await self._connection()
        async with _locked_db(self._db_path):
            await conn.execute(
                "INSERT OR REPLACE INTO vector_documents "
                "(id, content, embedding_json, metadata_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    document.id,
                    document.content,
                    json.dumps(document.embedding),
                    json.dumps(document.metadata),
                    document.created_at.isoformat(),
                ),
            )
            await conn.commit()

    async def add_batch(self, documents: list[Document]) -> None:
        """Add multiple documents."""
        if not documents:
            return
        hydrated: list[Document] = []
        for document in documents:
            if document.has_embedding:
                hydrated.append(document)
            else:
                hydrated.append(
                    document.with_embedding(await self._embedding_provider.embed(document.content))
                )

        conn = await self._connection()
        async with _locked_db(self._db_path):
            await conn.executemany(
                "INSERT OR REPLACE INTO vector_documents "
                "(id, content, embedding_json, metadata_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        document.id,
                        document.content,
                        json.dumps(document.embedding),
                        json.dumps(document.metadata),
                        document.created_at.isoformat(),
                    )
                    for document in hydrated
                ],
            )
            await conn.commit()

    async def get(self, document_id: str) -> Document | None:
        """Get a document by ID."""
        conn = await self._connection()
        async with conn.execute(
            "SELECT id, content, embedding_json, metadata_json, created_at "
            "FROM vector_documents WHERE id = ?",
            (document_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return _row_to_document(row) if row is not None else None

    async def delete(self, document_id: str) -> bool:
        """Delete a document."""
        conn = await self._connection()
        async with _locked_db(self._db_path):
            cursor = await conn.execute("DELETE FROM vector_documents WHERE id = ?", (document_id,))
            await conn.commit()
            return bool(cursor.rowcount > 0)

    async def search(
        self,
        query_embedding: tuple[float, ...],
        k: int = 10,
        filter: JSON | None = None,
    ) -> list[SearchResult]:
        """Search for similar documents using brute-force cosine similarity."""
        conn = await self._connection()
        async with conn.execute(
            "SELECT id, content, embedding_json, metadata_json, created_at FROM vector_documents"
        ) as cursor:
            rows = await cursor.fetchall()

        matches: list[tuple[float, Document]] = []
        for row in rows:
            document = _row_to_document(row)
            if not _matches_filter(document, filter):
                continue
            embedding = document.embedding
            if embedding is None:
                continue
            score = _cosine_similarity(query_embedding, embedding)
            matches.append((score, document))

        matches.sort(key=lambda item: item[0], reverse=True)
        return [
            SearchResult(document=document, score=score, rank=index)
            for index, (score, document) in enumerate(matches[:k])
        ]

    async def search_by_text(
        self,
        query_text: str,
        k: int = 10,
        filter: JSON | None = None,
    ) -> list[SearchResult]:
        """Search by text using the configured embedding provider."""
        query_embedding = await self._embedding_provider.embed(query_text)
        return await self.search(query_embedding=query_embedding, k=k, filter=filter)

    async def count(self) -> int:
        """Get total number of documents."""
        conn = await self._connection()
        async with conn.execute("SELECT COUNT(*) FROM vector_documents") as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row is not None else 0

    async def clear(self) -> None:
        """Remove all documents."""
        conn = await self._connection()
        async with _locked_db(self._db_path):
            await conn.execute("DELETE FROM vector_documents")
            await conn.commit()
