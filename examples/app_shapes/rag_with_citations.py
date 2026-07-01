"""App shape: grounded RAG — every answer traces back to a retrieved source.

Use-case: answer a support question from a knowledge base AND prove the claim is
grounded — each cited fact links to a document that was actually retrieved. This
is the membership invariant that separates RAG from hallucination.

Best practice shown: retrieval (`VectorStore`) and provenance (`CitationTracker`)
are CEMAF primitives — you compose them, you don't rebuild a citation ledger.

Usage:
    uv run python examples/app_shapes/rag_with_citations.py
"""

import asyncio

from cemaf.citation import CitationTracker
from cemaf.core.enums import VerificationStatus
from cemaf.retrieval.factories import create_in_memory_vector_store
from cemaf.retrieval.protocols import Document

KNOWLEDGE_BASE = [
    Document(
        id="kb-refunds",
        content="Refunds are issued within 5 business days of an approved return.",
        metadata={"title": "Refund Timing"},
    ),
    Document(
        id="kb-returns",
        content="Returns are accepted within 30 days of delivery with a receipt.",
        metadata={"title": "Return Window"},
    ),
    Document(
        id="kb-shipping",
        content="Standard shipping takes 3 to 7 business days.",
        metadata={"title": "Shipping Times"},
    ),
    Document(
        id="kb-hours",
        content="Support is available Monday to Friday, 9am to 5pm Pacific.",
        metadata={"title": "Support Hours"},
    ),
]


async def main() -> None:
    store = create_in_memory_vector_store()
    await store.add_batch(KNOWLEDGE_BASE)

    question = "How long until I get my refund after returning something?"
    results = await store.search_by_text(question, k=2)

    # Provenance: turn the retrieved results into tracked citations, then bind the
    # answer to exactly those citations as a cited fact.
    tracker = CitationTracker()
    citations = tracker.track_search_results(results)
    answer = results[0].content
    fact = tracker.create_cited_fact(
        fact=answer,
        citations=citations,
        confidence=0.9,
        verification_status=VerificationStatus.UNVERIFIED,
    )

    # Groundedness invariant: the fact is cited, and every citation points at a
    # document that was actually in the knowledge base / retrieved set.
    kb_ids = {doc.id for doc in KNOWLEDGE_BASE}
    retrieved_ids = {r.id for r in results}
    assert fact.is_cited
    assert fact.citation_count == len(results)
    assert all(c.source_id in kb_ids for c in citations)
    assert all(c.source_id in retrieved_ids for c in citations)

    report = tracker.get_citation_report()
    print(f"question      : {question}")
    print(f"answer        : {answer}")
    print(f"grounded      : {fact.is_cited} ({fact.citation_count} citations)")
    for citation in citations:
        print(f"  [{citation.source_id}] {citation.title} (score {citation.confidence:.3f})")
    print(f"citation_rate : {report['citation_rate']:.0%}")


if __name__ == "__main__":
    asyncio.run(main())
