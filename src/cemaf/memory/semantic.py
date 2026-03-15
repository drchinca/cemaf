"""Semantic memory bridge — embedding-based memory search."""

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol, runtime_checkable

from cemaf.core.enums import MemoryScope
from cemaf.core.types import JSON
from cemaf.core.utils import utc_now
from cemaf.memory.base import MemoryItem
from cemaf.memory.protocols import MemoryStore as MemoryStoreProtocol
from cemaf.memory.scoring import MemoryScorer, ScoredMemoryItem
from cemaf.retrieval.protocols import Document, EmbeddingProvider, SearchResult, VectorStore


@dataclass(frozen=True)
class MemoryQuery:
    """Query for semantic memory search."""

    text: str | None = None
    scope: MemoryScope | None = None
    scopes: tuple[MemoryScope, ...] | None = None
    min_confidence: float = 0.0
    max_age: timedelta | None = None
    limit: int = 10
    scope_path: str | None = None  # Filter to items under this hierarchical scope path


@dataclass(frozen=True)
class MemorySearchResult:
    """A scored memory search result."""

    item: MemoryItem
    similarity: float
    combined_score: float
    rank: int = 0


@runtime_checkable
class SemanticMemoryStore(Protocol):
    """Protocol for semantic memory with embedding-based search."""

    async def store(
        self,
        item: MemoryItem,
        *,
        content_for_embedding: str | None = None,
    ) -> None: ...

    async def search(self, query: MemoryQuery) -> tuple[MemorySearchResult, ...]: ...

    async def get(self, scope: MemoryScope, key: str) -> MemoryItem | None: ...

    async def delete(self, scope: MemoryScope, key: str) -> bool: ...

    async def cleanup_expired(self) -> int: ...


class DefaultSemanticMemoryStore:
    """Bridges MemoryStore + VectorStore + EmbeddingProvider + MemoryScorer."""

    def __init__(
        self,
        *,
        memory_store: MemoryStoreProtocol,
        vector_store: VectorStore,
        embedding_provider: EmbeddingProvider,
        scorer: MemoryScorer,
    ) -> None:
        self._memory_store = memory_store
        self._vector_store = vector_store
        self._embedding_provider = embedding_provider
        self._scorer = scorer

    async def store(
        self,
        item: MemoryItem,
        *,
        content_for_embedding: str | None = None,
    ) -> None:
        """Store item in both key-value and vector stores."""
        await self._memory_store.set(item=item)

        embed_text = content_for_embedding or self._item_to_embed_text(item=item)
        embedding = await self._embedding_provider.embed(text=embed_text)

        doc = Document(
            id=item.full_key,
            content=embed_text,
            embedding=embedding,
            metadata={
                "scope": item.scope.value,
                "key": item.key,
                "confidence": float(item.confidence),
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat(),
            },
            created_at=item.created_at,
        )
        await self._vector_store.add(document=doc)

    async def search(self, query: MemoryQuery) -> tuple[MemorySearchResult, ...]:
        """Search memory using semantic similarity and temporal decay."""
        if query.text is not None:
            return await self._semantic_search(query=query)
        return await self._scope_search(query=query)

    async def get(self, scope: MemoryScope, key: str) -> MemoryItem | None:
        """Direct key-value lookup."""
        return await self._memory_store.get(scope=scope, key=key)

    async def delete(self, scope: MemoryScope, key: str) -> bool:
        """Delete from both stores."""
        full_key = f"{scope.value}:{key}"
        await self._vector_store.delete(document_id=full_key)
        return await self._memory_store.delete(scope=scope, key=key)

    async def cleanup_expired(self) -> int:
        """Clean up expired items from both stores."""
        return await self._memory_store.cleanup_expired()

    async def _semantic_search(
        self,
        query: MemoryQuery,
    ) -> tuple[MemorySearchResult, ...]:
        """Vector similarity search with temporal decay re-ranking."""
        if query.text is None:
            raise ValueError("Semantic search requires query.text to be set")

        search_filter = self._build_filter(query=query)
        # Fetch extra candidates for re-ranking after filtering
        vector_results: list[SearchResult] = await self._vector_store.search_by_text(
            query_text=query.text,
            k=query.limit * 3,
            filter=search_filter,
        )

        results: list[MemorySearchResult] = []
        for vr in vector_results:
            try:
                scope = MemoryScope(vr.document.metadata.get("scope", "session"))
            except ValueError:
                continue
            item = await self._memory_store.get(
                scope=scope,
                key=vr.document.metadata.get("key", vr.document.id),
            )
            if item is None:
                continue
            if not self._passes_filters(item=item, query=query):
                continue

            scored: ScoredMemoryItem = self._scorer.score(
                item=item,
                relevance=vr.score,
            )
            results.append(
                MemorySearchResult(
                    item=item,
                    similarity=vr.score,
                    combined_score=scored.score,
                )
            )

        # Sort by combined score, assign ranks, limit
        results.sort(key=lambda r: r.combined_score, reverse=True)
        ranked = tuple(
            MemorySearchResult(
                item=r.item,
                similarity=r.similarity,
                combined_score=r.combined_score,
                rank=i,
            )
            for i, r in enumerate(results[: query.limit])
        )
        return ranked

    async def _scope_search(
        self,
        query: MemoryQuery,
    ) -> tuple[MemorySearchResult, ...]:
        """Scope-filtered search with temporal decay scoring."""
        scopes = self._resolve_scopes(query=query)
        all_items: list[MemoryItem] = []
        for scope in scopes:
            items = await self._memory_store.list_by_scope(scope=scope)
            all_items.extend(items)

        # Filter
        filtered = [i for i in all_items if self._passes_filters(item=i, query=query)]
        if not filtered:
            return ()

        # Score and rank
        scored = self._scorer.score_batch(items=tuple(filtered))
        results = tuple(
            MemorySearchResult(
                item=s.item,
                similarity=0.0,
                combined_score=s.score,
                rank=i,
            )
            for i, s in enumerate(scored[: query.limit])
        )
        return results

    def _resolve_scopes(self, query: MemoryQuery) -> tuple[MemoryScope, ...]:
        """Resolve which scopes to search."""
        if query.scopes:
            return query.scopes
        if query.scope:
            return (query.scope,)
        return tuple(MemoryScope)

    def _build_filter(self, query: MemoryQuery) -> JSON | None:
        """Build a vector store metadata filter."""
        if query.scope:
            return {"scope": query.scope.value}
        if query.scopes:
            return {"scope": {"$in": [s.value for s in query.scopes]}}
        return None

    def _passes_filters(self, *, item: MemoryItem, query: MemoryQuery) -> bool:
        """Check if item passes query filters."""
        if float(item.confidence) < query.min_confidence:
            return False
        if item.is_expired:
            return False
        if query.max_age is not None:
            age = utc_now() - item.updated_at
            if age > query.max_age:
                return False
        return not (
            query.scope_path is not None
            and item.scope_path is not None
            and not item.scope_path.startswith(query.scope_path)
        )

    @staticmethod
    def _item_to_embed_text(item: MemoryItem) -> str:
        """Convert a MemoryItem's value to embeddable text."""
        return f"{item.key}: {json.dumps(item.value, default=str)}"
