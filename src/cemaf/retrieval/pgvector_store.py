"""pgvector-backed VectorStore implementation.

Production-grade vector storage using PostgreSQL + pgvector extension:
- asyncpg connection pool with lazy initialization
- HNSW index for approximate nearest-neighbor search (cosine distance)
- GIN index on metadata for server-side JSON filtering
- Bulk ingest via copy_records_to_table for high-throughput writes
- Tenant isolation column mirrors the PostgresMemoryStore convention
- Supports $in, $nin, $ne, $eq, $exclude filter operators on metadata fields
"""

import json
from datetime import datetime
from typing import Any

from cemaf.core.types import JSON
from cemaf.core.utils import utc_now
from cemaf.retrieval.protocols import Document, SearchResult


class PgVectorStore:
    """VectorStore backed by PostgreSQL with pgvector extension.

    Pool is initialized lazily; construction is synchronous. The pgvector
    Python package must be installed alongside asyncpg so that asyncpg knows
    how to encode/decode the vector type.
    """

    def __init__(
        self,
        *,
        dsn: str,
        dimension: int = 3072,
        pool_min: int = 2,
        pool_max: int = 10,
        schema: str = "cemaf",
        tenant_id: str = "default",
    ) -> None:
        self._dsn = dsn
        self._dimension = dimension
        self._pool_min = pool_min
        self._pool_max = pool_max
        self._schema = schema
        self._tenant_id = tenant_id
        self._pool: Any | None = None

    async def _ensure_pool(self) -> Any:
        if self._pool is not None:
            return self._pool
        try:
            import asyncpg
        except ImportError as exc:
            raise ImportError(
                "asyncpg is required for PgVectorStore. Install it with: pip install 'cemaf[postgres]'"
            ) from exc
        try:
            import pgvector.asyncpg  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "pgvector is required for PgVectorStore. Install it with: pip install 'cemaf[postgres]'"
            ) from exc

        import pgvector.asyncpg as pgv_asyncpg

        async def _init_conn(conn: Any) -> None:
            await pgv_asyncpg.register_vector(conn)

        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=self._pool_min,
            max_size=self._pool_max,
            command_timeout=30,
            init=_init_conn,
        )
        await self._ensure_schema()
        return self._pool

    async def _ensure_schema(self) -> None:
        s = self._schema
        dim = self._dimension
        ddl = f"""
            CREATE EXTENSION IF NOT EXISTS vector;
            CREATE TABLE IF NOT EXISTS {s}.vector_documents (
                id TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding vector({dim}),
                metadata JSONB,
                created_at TIMESTAMPTZ NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                PRIMARY KEY (tenant_id, id)
            );
            CREATE INDEX IF NOT EXISTS idx_vd_hnsw
                ON {s}.vector_documents
                USING hnsw (embedding vector_cosine_ops)
                WITH (m=16, ef_construction=64);
            CREATE INDEX IF NOT EXISTS idx_vd_metadata
                ON {s}.vector_documents USING GIN (metadata);
        """
        async with self._pool.acquire() as conn:
            await conn.execute(ddl)

    async def close(self) -> None:
        """Close the pool. Idempotent."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def _build_filter_sql(
        self,
        filter: JSON | None,
        params: list[Any],
    ) -> str:
        """Translate the filter dict into a SQL WHERE fragment.

        Operators supported:
        - scalar equality: {"field": value} → metadata->>'field' = $N
        - {"field": {"$in": [...]}} → metadata->>'field' = ANY($N)
        - {"field": {"$nin": [...]}} → NOT (metadata->>'field' = ANY($N))
        - {"field": {"$ne": v}} → metadata->>'field' != $N
        - {"field": {"$eq": v}} → metadata->>'field' = $N
        - {"field": {"$exclude": [...]}} → metadata->>'field' != ALL($N)
        """
        if not filter:
            return ""
        clauses: list[str] = []
        for field, expression in filter.items():
            if isinstance(expression, dict):
                for op, operand in expression.items():
                    idx = len(params) + 1
                    if op == "$in":
                        params.append([str(v) for v in operand])
                        clauses.append(f"metadata->>'{field}' = ANY(${idx}::text[])")
                    elif op == "$nin":
                        params.append([str(v) for v in operand])
                        clauses.append(f"NOT (metadata->>'{field}' = ANY(${idx}::text[]))")
                    elif op == "$ne":
                        params.append(str(operand))
                        clauses.append(f"metadata->>'{field}' != ${idx}")
                    elif op == "$eq":
                        params.append(str(operand))
                        clauses.append(f"metadata->>'{field}' = ${idx}")
                    elif op == "$exclude":
                        params.append([str(v) for v in operand])
                        clauses.append(f"metadata->>'{field}' != ALL(${idx}::text[])")
                    else:
                        raise ValueError(f"Unsupported filter operator: {op}")
            else:
                # Scalar equality uses JSONB containment for type-correct matching
                idx = len(params) + 1
                params.append(json.dumps({field: expression}))
                clauses.append(f"metadata @> ${idx}::jsonb")
        return " AND ".join(clauses)

    def _row_to_document(self, row: Any) -> Document:
        metadata_raw = row["metadata"]
        if isinstance(metadata_raw, str):
            metadata: JSON = json.loads(metadata_raw)
        elif metadata_raw is None:
            metadata = {}
        else:
            metadata = dict(metadata_raw)

        embedding_raw = row["embedding"]
        if embedding_raw is None:
            embedding: tuple[float, ...] | None = None
        else:
            # pgvector returns a numpy-like array or list; normalize to tuple
            embedding = tuple(float(v) for v in embedding_raw)

        created_at = row["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        return Document(
            id=row["id"],
            content=row["content"],
            embedding=embedding,
            metadata=metadata,
            created_at=created_at,
        )

    async def add(self, document: Document) -> None:
        """Add a single document; delegates to add_batch for code reuse."""
        await self.add_batch([document])

    async def add_batch(self, documents: list[Document]) -> None:
        """Bulk-insert documents using copy_records_to_table for throughput.

        copy_records_to_table is significantly faster than individual INSERTs
        but does not support ON CONFLICT; we rely on the primary key to
        prevent duplicates by deleting first then copying.
        """
        if not documents:
            return
        pool = await self._ensure_pool()
        s = self._schema

        records = []
        for doc in documents:
            embedding_list = list(doc.embedding) if doc.embedding is not None else None
            metadata_str = json.dumps(doc.metadata) if doc.metadata else "{}"
            created_at = doc.created_at if isinstance(doc.created_at, datetime) else utc_now()
            records.append(
                (
                    doc.id,
                    doc.content,
                    embedding_list,
                    metadata_str,
                    created_at,
                    self._tenant_id,
                )
            )

        async with pool.acquire() as conn:
            # Upsert: delete existing rows for these ids then bulk copy
            ids = [r[0] for r in records]
            await conn.execute(
                f"DELETE FROM {s}.vector_documents WHERE tenant_id = $1 AND id = ANY($2::text[])",
                self._tenant_id,
                ids,
            )
            await conn.copy_records_to_table(
                f"{s}.vector_documents",
                records=records,
                columns=["id", "content", "embedding", "metadata", "created_at", "tenant_id"],
            )

    async def get(self, document_id: str) -> Document | None:
        """Retrieve a document by ID within this tenant."""
        pool = await self._ensure_pool()
        s = self._schema
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT id, content, embedding, metadata, created_at "
                f"FROM {s}.vector_documents "
                f"WHERE tenant_id = $1 AND id = $2",
                self._tenant_id,
                document_id,
            )
        if row is None:
            return None
        return self._row_to_document(row)

    async def delete(self, document_id: str) -> bool:
        """Delete a document, returning True if it existed."""
        pool = await self._ensure_pool()
        s = self._schema
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM {s}.vector_documents WHERE tenant_id = $1 AND id = $2",
                self._tenant_id,
                document_id,
            )
        return int(result.split()[-1]) > 0

    async def search(
        self,
        query_embedding: tuple[float, ...],
        k: int = 10,
        filter: JSON | None = None,
    ) -> list[SearchResult]:
        """Approximate nearest-neighbor search using HNSW cosine distance operator."""
        pool = await self._ensure_pool()
        s = self._schema

        params: list[Any] = [list(query_embedding), self._tenant_id, k]
        filter_sql = self._build_filter_sql(filter, params)

        where = "tenant_id = $2"
        if filter_sql:
            where += f" AND {filter_sql}"

        query = (
            f"SELECT id, content, embedding, metadata, created_at, "
            f"1 - (embedding <=> $1) AS score "
            f"FROM {s}.vector_documents "
            f"WHERE {where} "
            f"ORDER BY embedding <=> $1 "
            f"LIMIT $3"
        )

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        results = []
        for rank, row in enumerate(rows):
            doc = self._row_to_document(row)
            score = float(row["score"])
            results.append(SearchResult(document=doc, score=score, rank=rank))
        return results

    async def search_by_text(
        self,
        query_text: str,
        k: int = 10,
        filter: JSON | None = None,
    ) -> list[SearchResult]:
        """Not implemented at this layer — requires an EmbeddingProvider.

        Callers should embed query_text externally and call search() directly.
        Wire an EmbeddingProvider at the SemanticMemoryStore layer.
        """
        raise NotImplementedError(
            "PgVectorStore does not embed text internally. "
            "Embed the query using an EmbeddingProvider and call search() directly."
        )

    async def count(self) -> int:
        """Count documents for this tenant."""
        pool = await self._ensure_pool()
        s = self._schema
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT COUNT(*) AS n FROM {s}.vector_documents WHERE tenant_id = $1",
                self._tenant_id,
            )
        return int(row["n"])

    async def clear(self) -> None:
        """Delete all documents for this tenant."""
        pool = await self._ensure_pool()
        s = self._schema
        async with pool.acquire() as conn:
            await conn.execute(
                f"DELETE FROM {s}.vector_documents WHERE tenant_id = $1",
                self._tenant_id,
            )
