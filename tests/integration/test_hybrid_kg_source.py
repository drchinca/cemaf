"""Integration test: HybridRetriever fuses a real KnowledgeGraph as a third source.

Proves the graph_ranker seam is a live integration point: a real
`MemoryBackedKnowledgeGraph` (backed by `DefaultMemoryManager` + real
`InMemoryVectorStore`) ranks entities, and those rankings mix into the
`HybridRetriever` output alongside a real vector store — no mocks.

The graph slot is intentionally a callable, not a KG-shaped protocol:
this test also shows that any external ranker that yields `SearchResult`s
satisfies the seam. A future backend-owned graph ranker plugs in the same
way, delivering native ranked hits through the same lambda.
"""

from __future__ import annotations

import pytest

from cemaf.knowledge.factories import create_knowledge_graph
from cemaf.knowledge.models import EntityType, KGEntity
from cemaf.memory.factories import create_memory_manager
from cemaf.retrieval.hybrid import HybridRetriever
from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider
from cemaf.retrieval.protocols import Document, SearchResult


@pytest.mark.asyncio
async def test_kg_ranker_contributes_to_hybrid_output() -> None:
    """A doc surfaced only by the KG ranker reaches the merged output, alongside vector."""
    embedding_provider = MockEmbeddingProvider()
    vector_store = InMemoryVectorStore(embedding_provider=embedding_provider)

    # Seed the vector store with two docs.
    await vector_store.add(Document(id="mod:context", content="context engineering module"))
    await vector_store.add(Document(id="mod:memory", content="memory management module"))

    # Seed a real KG with two entities, one of which is NOT in the vector store.
    memory_manager = create_memory_manager()
    kg = create_knowledge_graph(memory_manager=memory_manager)
    await kg.add_entity(
        KGEntity(
            id="mod:context",
            type=EntityType.MODULE,
            name="context",
            description="context engineering module",
        )
    )
    await kg.add_entity(
        KGEntity(
            id="mod:retrieval",
            type=EntityType.MODULE,
            name="retrieval",
            description="hybrid retrieval module — vector plus graph",
        )
    )

    # Pre-fetch KG results at the retrieval boundary. The graph_ranker slot
    # is intentionally sync — callers adapt async backends by pre-fetching
    # or wrapping in a cache, keeping the retriever loop-agnostic.
    kg_entities = await kg.search(query="retrieval module", limit=10)

    def kg_ranker(query: str, k: int) -> list[SearchResult]:
        return [
            SearchResult(
                document=Document(id=e.id, content=e.description or e.name),
                score=1.0 / (i + 1),
                rank=i,
            )
            for i, e in enumerate(kg_entities[:k])
        ]

    retriever = HybridRetriever(
        vector_store=vector_store,
        graph_ranker=kg_ranker,
    )

    results = await retriever.search(query="retrieval module")
    ids = {r.document.id for r in results}

    # Vector store surfaces mod:context and mod:memory; the KG surfaces
    # mod:retrieval (not in the vector store). All three must reach the
    # fused output.
    assert "mod:retrieval" in ids, "KG-only entity failed to reach RRF output"
    assert "mod:context" in ids, "vector store hit dropped by fusion"
