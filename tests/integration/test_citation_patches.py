"""
Integration tests for Citation + Context Patches integration.

Tests that citations can be tracked as context patches for full provenance.
"""

import pytest

from cemaf.citation.models import Citation
from cemaf.citation.tracker import CitationTracker
from cemaf.context.context import Context
from cemaf.context.patch import PatchSource
from cemaf.retrieval.protocols import Document, SearchResult


class TestCitationPatches:
    """Integration tests for Citation + Context Patches."""

    @pytest.fixture
    def tracker(self) -> CitationTracker:
        """Create citation tracker."""
        return CitationTracker()

    @pytest.fixture
    def sample_search_result(self) -> SearchResult:
        """Create sample search result."""
        doc = Document(
            id="doc_123",
            content="CEMAF is a context engineering framework",
            metadata={
                "title": "CEMAF Documentation",
                "url": "https://example.com/cemaf",
                "author": "CEMAF Team",
            },
        )
        return SearchResult(document=doc, score=0.95, rank=1)

    @pytest.fixture
    def sample_citations(
        self, tracker: CitationTracker, sample_search_result: SearchResult
    ) -> list[Citation]:
        """Create sample citations."""
        return tracker.track_search_results([sample_search_result])

    @pytest.mark.asyncio
    async def test_create_cited_fact_patch(self, tracker: CitationTracker, sample_citations: list[Citation]):
        """Test creating a cited fact as a context patch."""
        fact = "CEMAF provides context management"
        cited_fact, patch = tracker.create_cited_fact_patch(
            fact=fact,
            citations=sample_citations,
            path="research.findings",
            correlation_id="run_123",
        )

        assert cited_fact is not None
        assert patch is not None
        assert patch.path.startswith("research.findings")
        assert patch.source == PatchSource.TOOL
        assert patch.source_id == "citation_tracker"
        assert patch.correlation_id == "run_123"
        assert patch.value["fact"] == fact
        assert len(patch.value["citations"]) == len(sample_citations)

    @pytest.mark.asyncio
    async def test_citation_patch_applies_to_context(
        self, tracker: CitationTracker, sample_citations: list[Citation]
    ):
        """Test that citation patches can be applied to context."""
        fact = "CEMAF uses immutable context"
        cited_fact, patch = tracker.create_cited_fact_patch(
            fact=fact,
            citations=sample_citations,
            path="facts",
        )

        context = Context(data={})
        new_context = context.apply(patch)

        # Verify fact is stored in context
        # Patch path is "facts.{fact_id}", so it creates nested structure
        fact_id = cited_fact.id
        assert "facts" in new_context.data
        assert fact_id in new_context.data["facts"]
        assert new_context.data["facts"][fact_id]["fact"] == fact
        assert len(new_context.data["facts"][fact_id]["citations"]) == len(sample_citations)

    @pytest.mark.asyncio
    async def test_citation_patch_includes_metadata(
        self, tracker: CitationTracker, sample_citations: list[Citation]
    ):
        """Test that citation patches include all necessary metadata."""
        fact = "Test fact"
        cited_fact, patch = tracker.create_cited_fact_patch(
            fact=fact,
            citations=sample_citations,
            confidence=0.95,
            verification_status="verified",
        )

        assert patch.value["fact_id"] == cited_fact.id
        assert patch.value["confidence"] == 0.95
        assert patch.value["verification_status"] == "verified"
        assert patch.value["citation_count"] == len(sample_citations)
        assert len(patch.value["citations"]) == len(sample_citations)

        # Verify citation data structure
        citation_data = patch.value["citations"][0]
        assert "id" in citation_data
        assert "source_id" in citation_data
        assert "title" in citation_data
