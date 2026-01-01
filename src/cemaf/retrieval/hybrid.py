"""
Hybrid retrieval - Combines vector and keyword search.

Uses Reciprocal Rank Fusion (RRF) to merge results.
"""

from collections.abc import Callable

from pydantic import BaseModel

from cemaf.core.types import JSON
from cemaf.retrieval.protocols import (
    Document,
    SearchResult,
    VectorStore,
)


class RetrievalConfig(BaseModel):
    """Configuration for hybrid retrieval."""

    model_config = {"frozen": True}

    # Number of results from each source
    vector_k: int = 20
    keyword_k: int = 20

    # Final number of results
    final_k: int = 10

    # RRF constant (higher = more weight to rank)
    rrf_k: int = 60

    # Weight for vector vs keyword (0.0 = keyword only, 1.0 = vector only)
    vector_weight: float = 0.5


def reciprocal_rank_fusion(
    rankings: list[list[str]],
    k: int = 60,
    weights: list[float] | None = None,
) -> list[tuple[str, float]]:
    """
    Merge multiple rankings using Reciprocal Rank Fusion.

    RRF score = sum(weight / (k + rank))

    Args:
        rankings: List of ranked document ID lists
        k: RRF constant
        weights: Optional weights for each ranking

    Returns:
        List of (doc_id, score) sorted by score descending
    """
    if weights is None:
        weights = [1.0] * len(rankings)

    scores: dict[str, float] = {}

    for ranking, weight in zip(rankings, weights, strict=False):
        for rank, doc_id in enumerate(ranking):
            if doc_id not in scores:
                scores[doc_id] = 0.0
            scores[doc_id] += weight / (k + rank + 1)

    # Sort by score descending
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_scores


class HybridRetriever:
    """
    Hybrid retriever combining vector and keyword search.

    Uses RRF to merge results from both sources.

    Usage:
        retriever = HybridRetriever(
            vector_store=my_vector_store,
            keyword_search=my_keyword_fn,
        )
        results = await retriever.search("query text", k=10)
    """

    def __init__(
        self,
        vector_store: VectorStore,
        keyword_search: Callable[[str, int], list[SearchResult]] | None = None,
        config: RetrievalConfig | None = None,
    ) -> None:
        self._vector_store = vector_store
        self._keyword_search = keyword_search
        self._config = config or RetrievalConfig()
        self._documents: dict[str, Document] = {}  # Cache for RRF merge

    async def search(
        self,
        query: str,
        k: int | None = None,
        filter: JSON | None = None,
    ) -> list[SearchResult]:
        """
        Perform hybrid search.

        Args:
            query: Search query
            k: Number of results (defaults to config.final_k)
            filter: Optional metadata filter

        Returns:
            List of SearchResults ordered by relevance
        """
        k = k or self._config.final_k

        # Vector search
        vector_results = await self._vector_store.search_by_text(
            query,
            k=self._config.vector_k,
            filter=filter,
        )

        # Cache documents and get ranking
        vector_ranking: list[str] = []
        for result in vector_results:
            self._documents[result.id] = result.document
            vector_ranking.append(result.id)

        # Keyword search (if available)
        keyword_ranking: list[str] = []
        if self._keyword_search:
            keyword_results = self._keyword_search(query, self._config.keyword_k)
            for result in keyword_results:
                self._documents[result.id] = result.document
                keyword_ranking.append(result.id)

        # Merge with RRF
        if keyword_ranking:
            merged = reciprocal_rank_fusion(
                [vector_ranking, keyword_ranking],
                k=self._config.rrf_k,
                weights=[self._config.vector_weight, 1 - self._config.vector_weight],
            )
        else:
            # Vector only
            merged = [(doc_id, 1.0 / (i + 1)) for i, doc_id in enumerate(vector_ranking)]

        # Build final results
        results: list[SearchResult] = []
        for rank, (doc_id, score) in enumerate(merged[:k]):
            doc = self._documents.get(doc_id)
            if doc:
                results.append(
                    SearchResult(
                        document=doc,
                        score=score,
                        rank=rank,
                    )
                )

        return results

    async def search_vector_only(
        self,
        query: str,
        k: int | None = None,
        filter: JSON | None = None,
    ) -> list[SearchResult]:
        """Search using only vector similarity."""
        k = k or self._config.final_k
        return await self._vector_store.search_by_text(query, k=k, filter=filter)
