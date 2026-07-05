"""Tests for hybrid retrieval with reciprocal rank fusion."""

import pytest

from cemaf.retrieval.hybrid import (
    HybridRetriever,
    RetrievalConfig,
    reciprocal_rank_fusion,
)
from cemaf.retrieval.protocols import Document, SearchResult


class TestReciprocalRankFusion:
    """Tests for the RRF pure function."""

    def test_single_ranking(self) -> None:
        """Single ranking returns scores based on rank position."""
        rankings = [["doc_a", "doc_b", "doc_c"]]
        results = reciprocal_rank_fusion(rankings=rankings, k=60)

        assert len(results) == 3
        # First doc has highest score
        assert results[0][0] == "doc_a"
        assert results[1][0] == "doc_b"
        assert results[2][0] == "doc_c"
        # Scores should be descending
        assert results[0][1] > results[1][1] > results[2][1]

    def test_two_rankings_with_overlap(self) -> None:
        """Overlapping doc IDs get combined scores."""
        rankings = [
            ["doc_a", "doc_b", "doc_c"],
            ["doc_b", "doc_c", "doc_d"],
        ]
        results = reciprocal_rank_fusion(rankings=rankings, k=60)
        result_dict = dict(results)

        # doc_b appears in both rankings, should have higher combined score
        # than doc_d which only appears in one
        assert result_dict["doc_b"] > result_dict["doc_d"]
        # All 4 unique docs should appear
        assert len(results) == 4

    def test_empty_rankings(self) -> None:
        """Empty rankings produce empty results."""
        results = reciprocal_rank_fusion(rankings=[], k=60)
        assert results == []

    def test_empty_individual_ranking(self) -> None:
        """An empty ranking list within rankings is handled."""
        rankings = [[], ["doc_a"]]
        results = reciprocal_rank_fusion(rankings=rankings, k=60)
        assert len(results) == 1
        assert results[0][0] == "doc_a"

    def test_custom_weights(self) -> None:
        """Weights affect score contribution per ranking."""
        rankings = [
            ["doc_a"],
            ["doc_b"],
        ]
        # Heavily weight first ranking
        results = reciprocal_rank_fusion(rankings=rankings, k=60, weights=[10.0, 1.0])
        result_dict = dict(results)

        assert result_dict["doc_a"] > result_dict["doc_b"]

    def test_k_parameter_affects_scores(self) -> None:
        """Different k values produce different score magnitudes."""
        rankings = [["doc_a", "doc_b"]]
        results_low_k = reciprocal_rank_fusion(rankings=rankings, k=1)
        results_high_k = reciprocal_rank_fusion(rankings=rankings, k=100)

        # Lower k produces higher individual scores (1/(k+rank+1))
        assert results_low_k[0][1] > results_high_k[0][1]

    def test_identical_rankings(self) -> None:
        """Same ranking repeated doubles the score."""
        rankings = [["doc_a"], ["doc_a"]]
        results = reciprocal_rank_fusion(rankings=rankings, k=60)

        single_results = reciprocal_rank_fusion(rankings=[["doc_a"]], k=60)

        assert abs(results[0][1] - 2 * single_results[0][1]) < 1e-10


class TestHybridRetriever:
    """Tests for HybridRetriever.search()."""

    @pytest.fixture
    def sample_documents(self) -> dict[str, Document]:
        return {
            "doc_1": Document(id="doc_1", content="Python programming guide"),
            "doc_2": Document(id="doc_2", content="Java programming guide"),
            "doc_3": Document(id="doc_3", content="Rust systems programming"),
        }

    @pytest.fixture
    def mock_vector_store(self, sample_documents):
        """Create a mock vector store that returns predetermined results."""

        class _MockVectorStore:
            def __init__(self, docs: dict[str, Document], results: list[SearchResult]):
                self._results = results

            async def search_by_text(self, query: str, k: int = 10, filter=None) -> list[SearchResult]:
                return self._results[:k]

            async def add(self, document):
                pass

            async def add_batch(self, documents):
                pass

            async def get(self, document_id):
                return None

            async def delete(self, document_id):
                return False

            async def search(self, query_embedding, k=10, filter=None):
                return []

            async def count(self):
                return 0

            async def clear(self):
                pass

        vector_results = [
            SearchResult(document=sample_documents["doc_1"], score=0.9, rank=0),
            SearchResult(document=sample_documents["doc_2"], score=0.7, rank=1),
        ]
        return _MockVectorStore(docs=sample_documents, results=vector_results)

    @pytest.mark.asyncio
    async def test_vector_only_search(self, mock_vector_store) -> None:
        """Search without keyword function uses vector results only."""
        retriever = HybridRetriever(
            vector_store=mock_vector_store,
            keyword_search=None,
        )
        results = await retriever.search(query="programming")

        assert len(results) == 2
        assert results[0].document.id == "doc_1"
        assert results[1].document.id == "doc_2"
        # Scores should be descending
        assert results[0].score >= results[1].score

    @pytest.mark.asyncio
    async def test_hybrid_search_with_keyword(self, mock_vector_store, sample_documents) -> None:
        """Search with keyword function merges both sources via RRF."""
        keyword_results = [
            SearchResult(document=sample_documents["doc_3"], score=0.8, rank=0),
            SearchResult(document=sample_documents["doc_1"], score=0.6, rank=1),
        ]

        def keyword_fn(query: str, k: int) -> list[SearchResult]:
            return keyword_results[:k]

        retriever = HybridRetriever(
            vector_store=mock_vector_store,
            keyword_search=keyword_fn,
        )
        results = await retriever.search(query="programming")

        # doc_1 appears in both rankings, should be boosted
        result_ids = [r.document.id for r in results]
        assert "doc_1" in result_ids
        assert "doc_3" in result_ids
        assert len(results) >= 2

    @pytest.mark.asyncio
    async def test_empty_results_from_both_sources(self) -> None:
        """Empty results from both sources produce empty output."""

        class _EmptyVectorStore:
            async def search_by_text(self, query, k=10, filter=None):
                return []

            async def add(self, document):
                pass

            async def add_batch(self, documents):
                pass

            async def get(self, document_id):
                return None

            async def delete(self, document_id):
                return False

            async def search(self, query_embedding, k=10, filter=None):
                return []

            async def count(self):
                return 0

            async def clear(self):
                pass

        def empty_keyword(query: str, k: int) -> list[SearchResult]:
            return []

        retriever = HybridRetriever(
            vector_store=_EmptyVectorStore(),
            keyword_search=empty_keyword,
        )
        results = await retriever.search(query="anything")
        assert results == []

    @pytest.mark.asyncio
    async def test_final_k_limits_results(self, mock_vector_store) -> None:
        """Results are limited to final_k."""
        config = RetrievalConfig(final_k=1)
        retriever = HybridRetriever(
            vector_store=mock_vector_store,
            config=config,
        )
        results = await retriever.search(query="programming")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_vector_only_method(self, mock_vector_store) -> None:
        """search_vector_only bypasses RRF entirely."""
        retriever = HybridRetriever(
            vector_store=mock_vector_store,
            keyword_search=lambda q, k: [],
        )
        results = await retriever.search_vector_only(query="programming")
        assert len(results) == 2
        assert results[0].score == 0.9


class TestGraphSource:
    """Graph ranker slot participates in RRF alongside vector (and keyword)."""

    @pytest.fixture
    def sample_documents(self) -> dict[str, Document]:
        return {
            "doc_1": Document(id="doc_1", content="Python programming guide"),
            "doc_2": Document(id="doc_2", content="Java programming guide"),
            "doc_3": Document(id="doc_3", content="Rust systems programming"),
            "doc_4": Document(id="doc_4", content="Graph databases in practice"),
        }

    @pytest.fixture
    def vector_store_returning(self, sample_documents):
        """Vector store whose two hits are doc_1 and doc_2."""

        class _V:
            async def search_by_text(self, query, k=10, filter=None):
                return [
                    SearchResult(document=sample_documents["doc_1"], score=0.9, rank=0),
                    SearchResult(document=sample_documents["doc_2"], score=0.7, rank=1),
                ][:k]

            async def add(self, document): ...
            async def add_batch(self, documents): ...
            async def get(self, document_id):
                return None

            async def delete(self, document_id):
                return False

            async def search(self, query_embedding, k=10, filter=None):
                return []

            async def count(self):
                return 0

            async def clear(self): ...

        return _V()

    @pytest.mark.asyncio
    async def test_graph_only_source_adds_docs_not_in_vector(
        self, vector_store_returning, sample_documents
    ) -> None:
        """A doc surfaced only by the graph ranker appears in the merged output."""

        def graph_rank(query: str, k: int) -> list[SearchResult]:
            return [SearchResult(document=sample_documents["doc_4"], score=0.5, rank=0)][:k]

        retriever = HybridRetriever(
            vector_store=vector_store_returning,
            graph_ranker=graph_rank,
        )
        results = await retriever.search(query="q")
        ids = [r.document.id for r in results]
        assert "doc_4" in ids  # graph-only doc reached the merged output
        assert "doc_1" in ids  # vector's top hit still present

    @pytest.mark.asyncio
    async def test_all_three_sources_fuse(self, vector_store_returning, sample_documents) -> None:
        """Vector + keyword + graph all contribute; a doc in all three ranks first."""

        def keyword_fn(query: str, k: int) -> list[SearchResult]:
            return [
                SearchResult(document=sample_documents["doc_1"], score=0.8, rank=0),
                SearchResult(document=sample_documents["doc_3"], score=0.6, rank=1),
            ][:k]

        def graph_rank(query: str, k: int) -> list[SearchResult]:
            return [
                SearchResult(document=sample_documents["doc_1"], score=0.7, rank=0),
                SearchResult(document=sample_documents["doc_4"], score=0.5, rank=1),
            ][:k]

        retriever = HybridRetriever(
            vector_store=vector_store_returning,
            keyword_search=keyword_fn,
            graph_ranker=graph_rank,
        )
        results = await retriever.search(query="q")
        ids = [r.document.id for r in results]
        # doc_1 is the only doc appearing in all three rankings — it must lead.
        assert ids[0] == "doc_1"
        # Graph-only + keyword-only docs still merged in.
        assert "doc_4" in ids
        assert "doc_3" in ids

    @pytest.mark.asyncio
    async def test_graph_ranker_absent_matches_prior_two_way_behavior(
        self, vector_store_returning, sample_documents
    ) -> None:
        """Wiring only vector + keyword produces the same ordering as before the graph slot."""

        def keyword_fn(query: str, k: int) -> list[SearchResult]:
            return [SearchResult(document=sample_documents["doc_3"], score=0.8, rank=0)][:k]

        retriever = HybridRetriever(
            vector_store=vector_store_returning,
            keyword_search=keyword_fn,
        )
        results = await retriever.search(query="q")
        ids = {r.document.id for r in results}
        assert ids == {"doc_1", "doc_2", "doc_3"}


class TestRetrievalConfig:
    """Tests for RetrievalConfig defaults and immutability."""

    def test_default_values(self) -> None:
        config = RetrievalConfig()
        assert config.vector_k == 20
        assert config.keyword_k == 20
        assert config.final_k == 10
        assert config.rrf_k == 60
        assert config.vector_weight == 0.5

    def test_frozen(self) -> None:
        config = RetrievalConfig()
        with pytest.raises(Exception):
            config.final_k = 99  # type: ignore[misc]
