"""
Hybrid retrieval - Combines vector, keyword, and graph search.

Uses Reciprocal Rank Fusion (RRF) to merge results across up to three
sources. Graph and keyword sources are pluggable callables that return
``SearchResult`` lists, keeping the fusion vendor-neutral: a knowledge
graph adapter, a full-text index, or any external backend that can rank
documents by an opaque score satisfies the shape.
"""

from collections.abc import Callable

from pydantic import BaseModel

from cemaf.core.types import JSON
from cemaf.retrieval.protocols import (
    Document,
    SearchResult,
    VectorStore,
)

# Named callable types so signatures read intention, not shape.
KeywordSearchFn = Callable[[str, int], list[SearchResult]]
GraphRankerFn = Callable[[str, int], list[SearchResult]]


class RetrievalConfig(BaseModel):
    """Configuration for hybrid retrieval."""

    model_config = {"frozen": True}

    # Number of results from each source
    vector_k: int = 20
    keyword_k: int = 20
    graph_k: int = 20

    # Final number of results
    final_k: int = 10

    # RRF constant (higher = more weight to rank)
    rrf_k: int = 60

    # Weight for vector vs keyword (0.0 = keyword only, 1.0 = vector only).
    # Kept as-is for 2-way fusion; graph_weight below is a separate scalar
    # that only participates when a graph ranker is present.
    vector_weight: float = 0.5
    graph_weight: float = 0.5


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
    Hybrid retriever combining vector, keyword, and graph search.

    Uses RRF to merge results across the sources that are wired. Any
    combination is valid — vector-only, vector+keyword, vector+graph, or
    all three. The graph slot is a callable, not a KG SDK: adapters over
    knowledge graphs, full-text engines, or backend-native hybrid runtimes
    all satisfy the shape.

    Usage:
        retriever = HybridRetriever(
            vector_store=my_vector_store,
            keyword_search=my_keyword_fn,
            graph_ranker=my_kg_adapter.rank,
        )
        results = await retriever.search("query text", k=10)
    """

    def __init__(
        self,
        vector_store: VectorStore,
        keyword_search: KeywordSearchFn | None = None,
        graph_ranker: GraphRankerFn | None = None,
        config: RetrievalConfig | None = None,
    ) -> None:
        self._vector_store = vector_store
        self._keyword_search = keyword_search
        self._graph_ranker = graph_ranker
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
            filter: Optional metadata filter (vector source only)

        Returns:
            List of SearchResults ordered by relevance
        """
        k = k or self._config.final_k
        self._documents.clear()

        vector_ranking = await self._run_vector(query=query, filter=filter)
        keyword_ranking = self._run_source(fn=self._keyword_search, query=query, k=self._config.keyword_k)
        graph_ranking = self._run_source(fn=self._graph_ranker, query=query, k=self._config.graph_k)

        merged = self._fuse(
            vector_ranking=vector_ranking,
            keyword_ranking=keyword_ranking,
            graph_ranking=graph_ranking,
        )

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

    async def _run_vector(self, *, query: str, filter: JSON | None) -> list[str]:
        results = await self._vector_store.search_by_text(
            query,
            k=self._config.vector_k,
            filter=filter,
        )
        ranking: list[str] = []
        for result in results:
            self._documents[result.id] = result.document
            ranking.append(result.id)
        return ranking

    def _run_source(self, *, fn: KeywordSearchFn | GraphRankerFn | None, query: str, k: int) -> list[str]:
        if fn is None:
            return []
        ranking: list[str] = []
        for result in fn(query, k):
            self._documents[result.id] = result.document
            ranking.append(result.id)
        return ranking

    def _fuse(
        self,
        *,
        vector_ranking: list[str],
        keyword_ranking: list[str],
        graph_ranking: list[str],
    ) -> list[tuple[str, float]]:
        """Fuse whichever sources produced results with RRF.

        Only one source (vector) → return its ranking with 1/(rank+1) scores
        so behaviour matches the pre-3-way version. Two or three sources →
        RRF with the per-source weights currently configured (vector vs
        keyword split, plus graph_weight when the graph slot is present).
        """
        rankings: list[list[str]] = [vector_ranking]
        weights: list[float] = [self._config.vector_weight]

        if keyword_ranking:
            rankings.append(keyword_ranking)
            weights.append(1 - self._config.vector_weight)
        if graph_ranking:
            rankings.append(graph_ranking)
            weights.append(self._config.graph_weight)

        if len(rankings) == 1:
            return [(doc_id, 1.0 / (i + 1)) for i, doc_id in enumerate(vector_ranking)]

        return reciprocal_rank_fusion(
            rankings=rankings,
            k=self._config.rrf_k,
            weights=weights,
        )
