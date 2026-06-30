"""BYO VectorStore — CEMAF retrieval over your own store, no Pinecone.

Use-case: you already keep records in a plain dict / SQLite / Postgres table and
want semantic search without adopting a vendor SDK. Implement the `VectorStore`
protocol; CEMAF retrieval works against it unchanged.

Best practice shown: reuse CEMAF's shipped `cosine_similarity` and the injected
`EmbeddingProvider` instead of reinventing math or hard-coding an embedder.

Usage:
    uv run python examples/byo/byo_vector_store.py
"""

import asyncio

from cemaf.retrieval.memory_store import MockEmbeddingProvider, cosine_similarity
from cemaf.retrieval.protocols import (
    Document,
    EmbeddingProvider,
    SearchResult,
    VectorStore,
)


class DictVectorStore:
    """A protocol-correct VectorStore backed by a plain dict."""

    def __init__(self, embedding_provider: EmbeddingProvider) -> None:
        self._embeddings = embedding_provider
        self._docs: dict[str, Document] = {}

    async def add(self, document: Document) -> None:
        if not document.has_embedding:
            embedding = await self._embeddings.embed(document.content)
            document = document.with_embedding(embedding)
        self._docs[document.id] = document

    async def add_batch(self, documents: list[Document]) -> None:
        for document in documents:
            await self.add(document)

    async def get(self, document_id: str) -> Document | None:
        return self._docs.get(document_id)

    async def delete(self, document_id: str) -> bool:
        return self._docs.pop(document_id, None) is not None

    async def search(
        self,
        query_embedding: tuple[float, ...],
        k: int = 10,
        filter: dict[str, object] | None = None,
    ) -> list[SearchResult]:
        scored = [
            (doc, cosine_similarity(query_embedding, doc.embedding))
            for doc in self._docs.values()
            if doc.embedding is not None
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [
            SearchResult(document=doc, score=score, rank=rank) for rank, (doc, score) in enumerate(scored[:k])
        ]

    async def search_by_text(
        self,
        query_text: str,
        k: int = 10,
        filter: dict[str, object] | None = None,
    ) -> list[SearchResult]:
        query_embedding = await self._embeddings.embed(query_text)
        return await self.search(query_embedding, k=k, filter=filter)

    async def count(self) -> int:
        return len(self._docs)

    async def clear(self) -> None:
        self._docs.clear()


async def main() -> None:
    # Swap MockEmbeddingProvider for a real one (e.g. create_embedding_provider(
    # "openai")) and the SAME store gives semantically-ranked results — the mock
    # is deterministic-hash, so it proves the wiring, not retrieval quality.
    store = DictVectorStore(MockEmbeddingProvider())

    assert isinstance(store, VectorStore), "DictVectorStore must satisfy VectorStore"

    await store.add_batch(
        [
            Document(id="d1", content="Refund policy: returns accepted within 30 days."),
            Document(id="d2", content="Shipping is free on orders over $50."),
            Document(id="d3", content="Our office hours are 9am to 5pm Pacific."),
        ]
    )

    hits = await store.search_by_text("how long do I have to return an item?", k=2)

    # Proof: the protocol round-trip works — k ranked results, sorted by score desc.
    assert len(hits) == 2
    assert [h.rank for h in hits] == [0, 1]
    assert hits[0].score >= hits[1].score

    print(f"protocol conformance : {isinstance(store, VectorStore)}")
    print(f"documents indexed    : {await store.count()}")
    for hit in hits:
        print(f"  rank {hit.rank}  score {hit.score:.3f}  {hit.id}: {hit.content}")


if __name__ == "__main__":
    asyncio.run(main())
