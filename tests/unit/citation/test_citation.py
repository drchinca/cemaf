"""Tests for citation module."""

from datetime import datetime

import pytest
from pydantic import BaseModel

from cemaf.citation.eval import CitationMembershipEvaluator
from cemaf.citation.factories import (
    citation_tracker_registry,
    create_citation_tracker,
    create_citation_tracker_from_config,
)
from cemaf.citation.mock import (
    MockCitationTracker,
    create_mock_citation,
    create_mock_cited_fact,
)
from cemaf.citation.models import Citation, CitationRegistry, CitedFact
from cemaf.citation.registry import SourceRegistry, StaticSourceRegistry
from cemaf.citation.rules import CitationFormatRule, CitationMembershipRule, CitationRequiredRule
from cemaf.citation.tracker import CitationTracker
from cemaf.retrieval.protocols import Document, SearchResult

# =============================================================================
# Citation Model Tests
# =============================================================================


class TestCitation:
    """Tests for Citation model."""

    def test_create_citation(self) -> None:
        """Test creating a citation."""
        citation = Citation(
            id="cite-001",
            source_id="doc-001",
            source_type="document",
            title="Test Document",
        )
        assert citation.id == "cite-001"
        assert citation.source_id == "doc-001"
        assert citation.source_type == "document"
        assert citation.title == "Test Document"
        assert citation.confidence == 1.0

    def test_citation_with_all_fields(self) -> None:
        """Test citation with all optional fields."""
        date = datetime(2024, 1, 15)
        citation = Citation(
            id="cite-002",
            source_id="doc-002",
            source_type="url",
            title="Test Article",
            url="https://example.com/article",
            author="John Doe",
            date=date,
            page=42,
            section="Introduction",
            quote="The exact quoted text",
            confidence=0.95,
            metadata={"key": "value"},
        )
        assert citation.url == "https://example.com/article"
        assert citation.author == "John Doe"
        assert citation.date == date
        assert citation.page == 42
        assert citation.section == "Introduction"
        assert citation.quote == "The exact quoted text"
        assert citation.confidence == 0.95
        assert citation.metadata == {"key": "value"}

    def test_citation_to_dict(self) -> None:
        """Test converting citation to dictionary."""
        date = datetime(2024, 1, 15, 12, 0, 0)
        citation = Citation(
            id="cite-001",
            source_id="doc-001",
            source_type="document",
            title="Test Document",
            date=date,
        )
        data = citation.to_dict()

        assert data["id"] == "cite-001"
        assert data["source_id"] == "doc-001"
        assert data["source_type"] == "document"
        assert data["title"] == "Test Document"
        assert data["date"] == "2024-01-15T12:00:00"

    def test_citation_to_dict_none_date(self) -> None:
        """Test to_dict with None date."""
        citation = Citation(
            id="cite-001",
            source_id="doc-001",
            source_type="document",
        )
        data = citation.to_dict()
        assert data["date"] is None

    def test_citation_from_dict(self) -> None:
        """Test creating citation from dictionary."""
        data = {
            "id": "cite-001",
            "source_id": "doc-001",
            "source_type": "document",
            "title": "Test Document",
            "url": "https://example.com",
            "author": "Jane Doe",
            "date": "2024-01-15T12:00:00",
            "page": 10,
            "section": "Methods",
            "quote": "Quoted text",
            "confidence": 0.9,
            "metadata": {"extra": "info"},
        }
        citation = Citation.from_dict(data)

        assert citation.id == "cite-001"
        assert citation.source_id == "doc-001"
        assert citation.source_type == "document"
        assert citation.title == "Test Document"
        assert citation.url == "https://example.com"
        assert citation.author == "Jane Doe"
        assert citation.date == datetime(2024, 1, 15, 12, 0, 0)
        assert citation.page == 10
        assert citation.section == "Methods"
        assert citation.quote == "Quoted text"
        assert citation.confidence == 0.9
        assert citation.metadata == {"extra": "info"}

    def test_citation_from_dict_minimal(self) -> None:
        """Test from_dict with minimal required fields."""
        data = {
            "id": "cite-001",
            "source_id": "doc-001",
            "source_type": "document",
        }
        citation = Citation.from_dict(data)

        assert citation.id == "cite-001"
        assert citation.title == ""
        assert citation.url is None
        assert citation.date is None
        assert citation.confidence == 1.0

    def test_citation_from_search_result(self) -> None:
        """Test creating citation from SearchResult."""
        doc = Document(
            id="doc-001",
            content="This is the document content.",
            metadata={
                "title": "Source Document",
                "url": "https://example.com",
                "author": "Author Name",
                "date": "2024-01-15",
                "page": 5,
                "section": "Overview",
                "source_type": "url",
            },
        )
        result = SearchResult(
            document=doc,
            score=0.85,
            rank=1,
            metadata={"query": "test query"},
        )

        citation = Citation.from_search_result(result)

        assert citation.source_id == "doc-001"
        assert citation.source_type == "url"
        assert citation.title == "Source Document"
        assert citation.url == "https://example.com"
        assert citation.author == "Author Name"
        assert citation.date == datetime(2024, 1, 15)
        assert citation.page == 5
        assert citation.section == "Overview"
        assert citation.quote == "This is the document content."
        assert citation.confidence == 0.85
        assert citation.metadata["search_rank"] == 1
        assert citation.metadata["search_score"] == 0.85
        assert citation.metadata["query"] == "test query"
        assert citation.id.startswith("cite_")

    def test_citation_from_search_result_minimal(self) -> None:
        """Test from_search_result with minimal metadata."""
        doc = Document(
            id="doc-001",
            content="Document content",
        )
        result = SearchResult(document=doc, score=0.75, rank=0)

        citation = Citation.from_search_result(result)

        assert citation.source_id == "doc-001"
        assert citation.source_type == "document"
        assert citation.title == ""
        assert citation.url is None
        assert citation.confidence == 0.75

    def test_citation_from_search_result_invalid_date(self) -> None:
        """Test from_search_result with invalid date string."""
        doc = Document(
            id="doc-001",
            content="Content",
            metadata={"date": "invalid-date-format"},
        )
        result = SearchResult(document=doc, score=0.9, rank=0)

        citation = Citation.from_search_result(result)
        assert citation.date is None

    def test_citation_from_search_result_invalid_page(self) -> None:
        """Test from_search_result with invalid page value."""
        doc = Document(
            id="doc-001",
            content="Content",
            metadata={"page": "not-a-number"},
        )
        result = SearchResult(document=doc, score=0.9, rank=0)

        citation = Citation.from_search_result(result)
        assert citation.page is None

    def test_citation_from_search_result_score_normalization(self) -> None:
        """Test confidence is clamped to [0, 1]."""
        doc = Document(id="doc-001", content="Content")

        # Score above 1
        result = SearchResult(document=doc, score=1.5, rank=0)
        citation = Citation.from_search_result(result)
        assert citation.confidence == 1.0

        # Score below 0
        result = SearchResult(document=doc, score=-0.5, rank=0)
        citation = Citation.from_search_result(result)
        assert citation.confidence == 0.0


# =============================================================================
# CitedFact Model Tests
# =============================================================================


class TestCitedFact:
    """Tests for CitedFact model."""

    def test_create_cited_fact(self) -> None:
        """Test creating a cited fact."""
        citation = create_mock_citation()
        fact = CitedFact(
            id="fact-001",
            fact="The sky is blue.",
            citations=(citation,),
        )
        assert fact.id == "fact-001"
        assert fact.fact == "The sky is blue."
        assert len(fact.citations) == 1
        assert fact.confidence == 1.0
        assert fact.verification_status == "unverified"

    def test_is_cited_true(self) -> None:
        """Test is_cited returns True when citations exist."""
        citation = create_mock_citation()
        fact = CitedFact(
            id="fact-001",
            fact="Test fact",
            citations=(citation,),
        )
        assert fact.is_cited is True

    def test_is_cited_false(self) -> None:
        """Test is_cited returns False when no citations."""
        fact = CitedFact(
            id="fact-001",
            fact="Uncited fact",
            citations=(),
        )
        assert fact.is_cited is False

    def test_primary_citation(self) -> None:
        """Test primary_citation returns first citation."""
        citation1 = create_mock_citation(id="cite-001")
        citation2 = create_mock_citation(id="cite-002")
        fact = CitedFact(
            id="fact-001",
            fact="Fact with multiple citations",
            citations=(citation1, citation2),
        )
        assert fact.primary_citation is not None
        assert fact.primary_citation.id == "cite-001"

    def test_primary_citation_none(self) -> None:
        """Test primary_citation returns None when no citations."""
        fact = CitedFact(
            id="fact-001",
            fact="Uncited fact",
            citations=(),
        )
        assert fact.primary_citation is None

    def test_citation_count(self) -> None:
        """Test citation_count returns correct count."""
        citations = tuple(create_mock_citation(id=f"cite-{i}") for i in range(3))
        fact = CitedFact(
            id="fact-001",
            fact="Well-cited fact",
            citations=citations,
        )
        assert fact.citation_count == 3

    def test_citation_count_zero(self) -> None:
        """Test citation_count returns 0 when no citations."""
        fact = CitedFact(
            id="fact-001",
            fact="Uncited fact",
            citations=(),
        )
        assert fact.citation_count == 0


# =============================================================================
# CitationRegistry Tests
# =============================================================================


class TestCitationRegistry:
    """Tests for CitationRegistry."""

    def test_register_citation(self) -> None:
        """Test registering a citation."""
        registry = CitationRegistry()
        citation = create_mock_citation()

        registry.register(citation)

        assert registry.get_citation(citation.id) == citation

    def test_register_many(self) -> None:
        """Test registering multiple citations."""
        registry = CitationRegistry()
        citations = [create_mock_citation(id=f"cite-{i}") for i in range(3)]

        registry.register_many(citations)

        for c in citations:
            assert registry.get_citation(c.id) == c

    def test_get_citation_not_found(self) -> None:
        """Test get_citation returns None for unknown ID."""
        registry = CitationRegistry()
        assert registry.get_citation("unknown") is None

    def test_add_cited_fact(self) -> None:
        """Test adding a cited fact."""
        registry = CitationRegistry()
        cited_fact = create_mock_cited_fact()

        registry.add_cited_fact(cited_fact)

        facts = registry.get_cited_facts()
        assert len(facts) == 1
        assert facts[0] == cited_fact
        # Citations should be registered too
        for c in cited_fact.citations:
            assert registry.get_citation(c.id) == c

    def test_add_uncited_fact(self) -> None:
        """Test tracking an uncited fact."""
        registry = CitationRegistry()

        registry.add_uncited_fact("Uncited claim without sources.")

        uncited = registry.get_uncited_facts()
        assert len(uncited) == 1
        assert uncited[0] == "Uncited claim without sources."

    def test_get_all_citations(self) -> None:
        """Test getting all citations."""
        registry = CitationRegistry()
        citations = [create_mock_citation(id=f"cite-{i}") for i in range(3)]
        registry.register_many(citations)

        all_citations = registry.get_all_citations()

        assert len(all_citations) == 3

    def test_get_citation_report(self) -> None:
        """Test generating citation report."""
        registry = CitationRegistry()

        # Add a cited fact
        cited_fact = create_mock_cited_fact()
        registry.add_cited_fact(cited_fact)

        # Add uncited facts
        registry.add_uncited_fact("Uncited claim 1")
        registry.add_uncited_fact("Uncited claim 2")

        report = registry.get_citation_report()

        assert report["total_citations"] == 1
        assert report["total_cited_facts"] == 1
        assert report["total_uncited_facts"] == 2
        assert report["citation_rate"] == pytest.approx(1 / 3)
        assert len(report["citations"]) == 1

    def test_get_citation_report_empty(self) -> None:
        """Test report with no facts defaults to 100% rate."""
        registry = CitationRegistry()
        report = registry.get_citation_report()

        assert report["total_citations"] == 0
        assert report["citation_rate"] == 1.0

    def test_clear(self) -> None:
        """Test clearing the registry."""
        registry = CitationRegistry()
        registry.register(create_mock_citation())
        registry.add_cited_fact(create_mock_cited_fact(id="fact-001"))
        registry.add_uncited_fact("Uncited fact")

        registry.clear()

        assert len(registry.get_all_citations()) == 0
        assert len(registry.get_cited_facts()) == 0
        assert len(registry.get_uncited_facts()) == 0


# =============================================================================
# CitationTracker Tests
# =============================================================================


class TestCitationTracker:
    """Tests for CitationTracker."""

    def test_create_tracker(self) -> None:
        """Test creating a tracker with default registry."""
        tracker = CitationTracker()
        assert tracker.registry is not None

    def test_create_tracker_with_registry(self) -> None:
        """Test creating a tracker with custom registry."""
        registry = CitationRegistry()
        tracker = CitationTracker(registry=registry)
        assert tracker.registry is registry

    def test_track_search_result(self) -> None:
        """Test tracking a search result."""
        tracker = MockCitationTracker()
        doc = Document(
            id="doc-001",
            content="Document content",
            metadata={"title": "Test Document"},
        )
        result = SearchResult(document=doc, score=0.9, rank=0)

        citation = tracker.track_search_result(result)

        assert citation.source_id == "doc-001"
        assert citation.title == "Test Document"
        # Citation should be in registry
        assert tracker.get_citation(citation.id) == citation

    def test_track_search_results(self) -> None:
        """Test tracking multiple search results."""
        tracker = MockCitationTracker()
        docs = [Document(id=f"doc-{i}", content=f"Content {i}") for i in range(3)]
        results = [SearchResult(document=doc, score=0.9 - i * 0.1, rank=i) for i, doc in enumerate(docs)]

        citations = tracker.track_search_results(results)

        assert len(citations) == 3
        for citation in citations:
            assert tracker.get_citation(citation.id) == citation

    def test_create_cited_fact(self) -> None:
        """Test creating a cited fact through tracker."""
        tracker = MockCitationTracker()
        citation = create_mock_citation()

        cited_fact = tracker.create_cited_fact(
            fact="The Earth orbits the Sun.",
            citations=[citation],
            confidence=0.99,
            verification_status="verified",
        )

        assert cited_fact.fact == "The Earth orbits the Sun."
        assert cited_fact.citation_count == 1
        assert cited_fact.confidence == 0.99
        assert cited_fact.verification_status == "verified"
        # Should be in registry
        facts = tracker.get_cited_facts()
        assert len(facts) == 1

    def test_record_uncited_fact(self) -> None:
        """Test recording an uncited fact."""
        tracker = MockCitationTracker()

        tracker.record_uncited_fact("Unsupported claim without sources.")

        uncited = tracker.get_uncited_facts()
        assert len(uncited) == 1
        assert uncited[0] == "Unsupported claim without sources."

    def test_get_all_citations(self) -> None:
        """Test getting all tracked citations."""
        tracker = MockCitationTracker()
        doc = Document(id="doc-001", content="Content")
        result = SearchResult(document=doc, score=0.9, rank=0)

        tracker.track_search_result(result)

        all_citations = tracker.get_all_citations()
        assert len(all_citations) == 1

    def test_get_citation_report(self) -> None:
        """Test getting citation report through tracker."""
        tracker = MockCitationTracker()

        citation = create_mock_citation()
        tracker.create_cited_fact("Cited fact", [citation])
        tracker.record_uncited_fact("Uncited fact")

        report = tracker.get_citation_report()

        assert report["total_cited_facts"] == 1
        assert report["total_uncited_facts"] == 1

    def test_clear(self) -> None:
        """Test clearing the tracker."""
        tracker = MockCitationTracker()
        doc = Document(id="doc-001", content="Content")
        result = SearchResult(document=doc, score=0.9, rank=0)
        tracker.track_search_result(result)

        tracker.clear()

        assert len(tracker.get_all_citations()) == 0


# =============================================================================
# CitationRequiredRule Tests
# =============================================================================


class TestCitationRequiredRule:
    """Tests for CitationRequiredRule."""

    @pytest.mark.asyncio
    async def test_rule_name(self) -> None:
        """Test rule has name."""
        rule = CitationRequiredRule(name="test_citation_rule")
        assert rule.name == "test_citation_rule"

    @pytest.mark.asyncio
    async def test_cited_fact_with_citations_passes(self) -> None:
        """Test cited fact with sufficient citations passes."""
        rule = CitationRequiredRule(min_citations=1)
        cited_fact = create_mock_cited_fact()

        result = await rule.check(cited_fact)

        assert result.passed is True
        assert len(result.warnings) == 0

    @pytest.mark.asyncio
    async def test_cited_fact_insufficient_citations_warns(self) -> None:
        """Test cited fact with insufficient citations gets warning."""
        rule = CitationRequiredRule(min_citations=2)
        cited_fact = create_mock_cited_fact()  # Has 1 citation

        result = await rule.check(cited_fact)

        # Still passes (warnings only, never blocks)
        assert result.passed is True
        assert len(result.warnings) == 1
        assert result.warnings[0].code == "INSUFFICIENT_CITATIONS"

    @pytest.mark.asyncio
    async def test_citation_registry_with_uncited_facts_warns(self) -> None:
        """Test registry with uncited facts generates warnings."""
        rule = CitationRequiredRule()
        registry = CitationRegistry()
        registry.add_uncited_fact("Uncited claim 1")
        registry.add_uncited_fact("Uncited claim 2")

        result = await rule.check(registry)

        assert result.passed is True
        assert len(result.warnings) == 2
        assert all(w.code == "UNCITED_FACT" for w in result.warnings)

    @pytest.mark.asyncio
    async def test_citation_registry_without_uncited_passes(self) -> None:
        """Test registry without uncited facts passes cleanly."""
        rule = CitationRequiredRule()
        registry = CitationRegistry()
        registry.add_cited_fact(create_mock_cited_fact())

        result = await rule.check(registry)

        assert result.passed is True
        assert len(result.warnings) == 0

    @pytest.mark.asyncio
    async def test_list_of_cited_facts(self) -> None:
        """Test checking list of cited facts."""
        rule = CitationRequiredRule(min_citations=1)
        facts = [
            create_mock_cited_fact(id="fact-1"),
            CitedFact(id="fact-2", fact="Uncited fact", citations=()),
            create_mock_cited_fact(id="fact-3"),
        ]

        result = await rule.check(facts)

        assert result.passed is True
        assert len(result.warnings) == 1
        assert "facts[1]" in result.warnings[0].field

    @pytest.mark.asyncio
    async def test_dict_with_citations(self) -> None:
        """Test checking dict with citations key."""
        rule = CitationRequiredRule(min_citations=2)
        data = {"citations": [create_mock_citation()]}

        result = await rule.check(data)

        assert result.passed is True
        assert len(result.warnings) == 1
        assert result.warnings[0].code == "INSUFFICIENT_CITATIONS"

    @pytest.mark.asyncio
    async def test_long_uncited_fact_truncated_in_warning(self) -> None:
        """Test long uncited facts are truncated in warnings."""
        rule = CitationRequiredRule()
        registry = CitationRegistry()
        long_fact = "A" * 100  # Over 50 chars
        registry.add_uncited_fact(long_fact)

        result = await rule.check(registry)

        assert result.passed is True
        warning_msg = result.warnings[0].message
        assert "..." in warning_msg


# =============================================================================
# CitationFormatRule Tests
# =============================================================================


class TestCitationFormatRule:
    """Tests for CitationFormatRule."""

    @pytest.mark.asyncio
    async def test_rule_name(self) -> None:
        """Test rule has name."""
        rule = CitationFormatRule(name="format_rule")
        assert rule.name == "format_rule"

    @pytest.mark.asyncio
    async def test_citation_with_title_passes(self) -> None:
        """Test citation with title passes when title required."""
        rule = CitationFormatRule(require_title=True, require_url=False)
        citation = create_mock_citation(title="Valid Title")

        result = await rule.check(citation)

        assert result.passed is True
        assert len(result.warnings) == 0

    @pytest.mark.asyncio
    async def test_citation_missing_title_warns(self) -> None:
        """Test citation missing title generates warning."""
        rule = CitationFormatRule(require_title=True)
        citation = Citation(
            id="cite-001",
            source_id="doc-001",
            source_type="document",
            title="",  # Empty title
        )

        result = await rule.check(citation)

        assert result.passed is True
        assert len(result.warnings) == 1
        assert result.warnings[0].code == "MISSING_TITLE"

    @pytest.mark.asyncio
    async def test_citation_with_url_passes(self) -> None:
        """Test citation with URL passes when URL required."""
        rule = CitationFormatRule(require_url=True)
        citation = create_mock_citation(
            title="Title",
            url="https://example.com",
        )

        result = await rule.check(citation)

        assert result.passed is True
        assert len(result.warnings) == 0

    @pytest.mark.asyncio
    async def test_citation_missing_url_warns(self) -> None:
        """Test citation missing URL generates warning."""
        rule = CitationFormatRule(require_url=True)
        citation = create_mock_citation(title="Title", url=None)

        result = await rule.check(citation)

        assert result.passed is True
        assert len(result.warnings) == 1
        assert result.warnings[0].code == "MISSING_URL"

    @pytest.mark.asyncio
    async def test_invalid_confidence_warns(self) -> None:
        """Test citation with invalid confidence generates warning."""
        rule = CitationFormatRule(require_title=False)
        # Need to create citation with invalid confidence manually
        # Since dataclass doesn't prevent this
        citation = Citation(
            id="cite-001",
            source_id="doc-001",
            source_type="document",
            title="Title",
            confidence=1.5,  # Invalid, should be 0-1
        )

        result = await rule.check(citation)

        assert result.passed is True
        assert any(w.code == "INVALID_CONFIDENCE" for w in result.warnings)

    @pytest.mark.asyncio
    async def test_negative_confidence_warns(self) -> None:
        """Test citation with negative confidence generates warning."""
        rule = CitationFormatRule(require_title=False)
        citation = Citation(
            id="cite-001",
            source_id="doc-001",
            source_type="document",
            title="Title",
            confidence=-0.5,
        )

        result = await rule.check(citation)

        assert result.passed is True
        assert any(w.code == "INVALID_CONFIDENCE" for w in result.warnings)

    @pytest.mark.asyncio
    async def test_list_of_citations(self) -> None:
        """Test checking list of citations."""
        rule = CitationFormatRule(require_title=True)
        citations = [
            create_mock_citation(id="cite-1", title="Has Title"),
            Citation(
                id="cite-2",
                source_id="doc-002",
                source_type="document",
                title="",
            ),
        ]

        result = await rule.check(citations)

        assert result.passed is True
        assert len(result.warnings) == 1
        assert "cite-2" in result.warnings[0].message

    @pytest.mark.asyncio
    async def test_cited_fact(self) -> None:
        """Test checking CitedFact."""
        rule = CitationFormatRule(require_url=True)
        citation_no_url = Citation(
            id="cite-001",
            source_id="doc-001",
            source_type="document",
            title="Title",
            url=None,
        )
        cited_fact = CitedFact(
            id="fact-001",
            fact="Test fact",
            citations=(citation_no_url,),
        )

        result = await rule.check(cited_fact)

        assert result.passed is True
        assert len(result.warnings) == 1
        assert result.warnings[0].code == "MISSING_URL"


# =============================================================================
# Mock Utilities Tests
# =============================================================================


class TestMockUtilities:
    """Tests for mock utilities."""

    def test_create_mock_citation_defaults(self) -> None:
        """Test create_mock_citation with defaults."""
        citation = create_mock_citation()

        assert citation.id == "cite-001"
        assert citation.source_id == "doc-001"
        assert citation.source_type == "document"
        assert citation.title == "Mock Source"

    def test_create_mock_citation_custom(self) -> None:
        """Test create_mock_citation with custom values."""
        citation = create_mock_citation(
            id="custom-cite",
            source_id="custom-doc",
            source_type="url",
            title="Custom Source",
            url="https://custom.example.com",
            confidence=0.8,
        )

        assert citation.id == "custom-cite"
        assert citation.source_id == "custom-doc"
        assert citation.source_type == "url"
        assert citation.title == "Custom Source"
        assert citation.url == "https://custom.example.com"
        assert citation.confidence == 0.8

    def test_create_mock_cited_fact_defaults(self) -> None:
        """Test create_mock_cited_fact with defaults."""
        cited_fact = create_mock_cited_fact()

        assert cited_fact.id == "fact-001"
        assert cited_fact.fact == "This is a test fact."
        assert cited_fact.citation_count == 1

    def test_create_mock_cited_fact_custom(self) -> None:
        """Test create_mock_cited_fact with custom values."""
        custom_citations = [
            create_mock_citation(id="cite-a"),
            create_mock_citation(id="cite-b"),
        ]
        cited_fact = create_mock_cited_fact(
            id="custom-fact",
            fact="Custom test fact.",
            citations=custom_citations,
            confidence=0.95,
        )

        assert cited_fact.id == "custom-fact"
        assert cited_fact.fact == "Custom test fact."
        assert cited_fact.citation_count == 2
        assert cited_fact.confidence == 0.95

    def test_mock_citation_tracker(self) -> None:
        """Test MockCitationTracker works without event bus."""
        tracker = MockCitationTracker()

        # Should work without errors even without event bus
        doc = Document(id="doc-001", content="Content")
        result = SearchResult(document=doc, score=0.9, rank=0)

        citation = tracker.track_search_result(result)
        tracker.create_cited_fact("Test fact", [citation])
        tracker.record_uncited_fact("Uncited fact")
        tracker.clear()

        # All operations should complete without error
        assert len(tracker.get_all_citations()) == 0


class TestCitationFactories:
    """Tests for citation tracker factories."""

    def test_create_default_citation_tracker(self) -> None:
        """Test creating the built-in default tracker."""
        tracker = create_citation_tracker()

        assert isinstance(tracker, CitationTracker)

    def test_create_mock_citation_tracker(self) -> None:
        """Test creating the built-in mock tracker."""
        tracker = create_citation_tracker(backend="mock")

        assert isinstance(tracker, MockCitationTracker)

    def test_register_custom_citation_tracker_backend(self) -> None:
        """Test custom citation tracker registration without editing framework source."""
        captured: dict[str, object] = {}

        class CustomCitationTracker(MockCitationTracker):
            pass

        def factory(**kwargs: object) -> CustomCitationTracker:
            captured.update(kwargs)
            return CustomCitationTracker()

        citation_tracker_registry.register(backend="unit_custom", factory=factory)

        tracker = create_citation_tracker(
            backend="unit_custom",
            enable_tracking=False,
            require_citations=True,
            citation_format="ieee",
            enable_validation=False,
        )

        assert isinstance(tracker, CustomCitationTracker)
        assert captured["enable_tracking"] is False
        assert captured["require_citations"] is True
        assert captured["citation_format"] == "ieee"
        assert captured["enable_validation"] is False

    def test_create_registered_citation_tracker_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test environment-selected custom citation tracker backends."""
        captured: dict[str, object] = {}

        class EnvCitationTracker(MockCitationTracker):
            pass

        def factory(**kwargs: object) -> EnvCitationTracker:
            captured.update(kwargs)
            return EnvCitationTracker()

        citation_tracker_registry.register(backend="env_custom", factory=factory)
        monkeypatch.setenv("CEMAF_CITATION_BACKEND", "env_custom")
        monkeypatch.setenv("CEMAF_CITATION_ENABLE_TRACKING", "false")
        monkeypatch.setenv("CEMAF_CITATION_REQUIRE_CITATIONS", "true")
        monkeypatch.setenv("CEMAF_CITATION_CITATION_FORMAT", "chicago")
        monkeypatch.setenv("CEMAF_CITATION_ENABLE_VALIDATION", "false")

        tracker = create_citation_tracker_from_config()

        assert isinstance(tracker, EnvCitationTracker)
        assert captured["enable_tracking"] is False
        assert captured["require_citations"] is True
        assert captured["citation_format"] == "chicago"
        assert captured["enable_validation"] is False

    def test_unsupported_citation_tracker_backend_names_registry(self) -> None:
        """Test unknown citation tracker backend error points to registry extension."""
        with pytest.raises(ValueError, match="citation_tracker_registry.register"):
            create_citation_tracker(backend="missing_citation_backend")


# =============================================================================
# StaticSourceRegistry Tests
# =============================================================================


class TestStaticSourceRegistry:
    """Tests for StaticSourceRegistry."""

    def test_is_known_true(self) -> None:
        """Test known source_id returns True."""
        registry = StaticSourceRegistry.from_iterable(["doc-001", "doc-002"])
        assert registry.is_known("doc-001") is True

    def test_is_known_false(self) -> None:
        """Test unknown source_id returns False."""
        registry = StaticSourceRegistry.from_iterable(["doc-001"])
        assert registry.is_known("doc-999") is False

    def test_satisfies_protocol(self) -> None:
        """Test StaticSourceRegistry satisfies the SourceRegistry protocol."""
        registry = StaticSourceRegistry.from_iterable(["doc-001"])
        assert isinstance(registry, SourceRegistry)


# =============================================================================
# CitationMembershipRule Tests — the blocking rule
# =============================================================================


class TestCitationMembershipRule:
    """Tests for CitationMembershipRule."""

    @pytest.mark.asyncio
    async def test_known_source_passes(self) -> None:
        """Test citation with known source_id passes with no errors."""
        registry = StaticSourceRegistry.from_iterable(["doc-001"])
        rule = CitationMembershipRule(registry=registry)
        citation = create_mock_citation(source_id="doc-001")

        result = await rule.check(citation)

        assert result.passed is True
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_unknown_source_blocks(self) -> None:
        """Test citation with unknown source_id fails with a blocking error."""
        registry = StaticSourceRegistry.from_iterable(["doc-001"])
        rule = CitationMembershipRule(registry=registry)
        citation = create_mock_citation(id="cite-fake", source_id="fabricated-source")

        result = await rule.check(citation)

        assert result.passed is False
        assert len(result.errors) == 1
        assert result.errors[0].code == "UNKNOWN_SOURCE"
        assert result.errors[0].value == "fabricated-source"

    @pytest.mark.asyncio
    async def test_cited_fact_with_unknown_source_blocks(self) -> None:
        """Test CitedFact citing an unknown source_id fails."""
        registry = StaticSourceRegistry.from_iterable(["doc-001"])
        rule = CitationMembershipRule(registry=registry)
        fact = create_mock_cited_fact(
            citations=[create_mock_citation(source_id="not-real")],
        )

        result = await rule.check(fact)

        assert result.passed is False
        assert result.errors[0].code == "UNKNOWN_SOURCE"

    @pytest.mark.asyncio
    async def test_list_of_citations_mixed(self) -> None:
        """Test a list with one known and one unknown source_id blocks."""
        registry = StaticSourceRegistry.from_iterable(["doc-001"])
        rule = CitationMembershipRule(registry=registry)
        citations = [
            create_mock_citation(id="cite-1", source_id="doc-001"),
            create_mock_citation(id="cite-2", source_id="doc-fake"),
        ]

        result = await rule.check(citations)

        assert result.passed is False
        assert len(result.errors) == 1
        assert "cite-2" in result.errors[0].message

    @pytest.mark.asyncio
    async def test_dict_payload_with_nested_unknown_source_blocks(self) -> None:
        """Test common JSON answer payloads are enforced, not only Citation objects."""
        registry = StaticSourceRegistry.from_iterable(["doc-001"])
        rule = CitationMembershipRule(registry=registry)
        payload = {
            "answer": "grounded claim",
            "sections": [
                {
                    "citations": [
                        create_mock_citation(id="cite-good", source_id="doc-001").to_dict(),
                        create_mock_citation(id="cite-fake", source_id="not-in-registry").to_dict(),
                    ]
                }
            ],
        }

        result = await rule.check(payload)

        assert result.passed is False
        assert len(result.errors) == 1
        assert result.errors[0].value == "not-in-registry"
        assert "cite-fake" in result.errors[0].message

    @pytest.mark.asyncio
    async def test_stringified_payload_with_unknown_source_blocks(self) -> None:
        """Test executor-stringified answer payloads are inspected."""
        registry = StaticSourceRegistry.from_iterable(["doc-001"])
        rule = CitationMembershipRule(registry=registry)
        payload = {
            "answer": "grounded claim",
            "citations": [create_mock_citation(id="cite-fake", source_id="fake-doc").to_dict()],
        }

        result = await rule.check(str(payload))

        assert result.passed is False
        assert result.errors[0].value == "fake-doc"
        assert "cite-fake" in result.errors[0].message

    @pytest.mark.asyncio
    async def test_citation_registry_with_unknown_source_blocks(self) -> None:
        """Test CitationRegistry contents are enforced."""
        registry = StaticSourceRegistry.from_iterable(["doc-001"])
        rule = CitationMembershipRule(registry=registry)
        citation_registry = CitationRegistry()
        citation_registry.register(create_mock_citation(id="cite-good", source_id="doc-001"))
        citation_registry.register(create_mock_citation(id="cite-fake", source_id="fake-doc"))

        result = await rule.check(citation_registry)

        assert result.passed is False
        assert result.errors[0].value == "fake-doc"

    @pytest.mark.asyncio
    async def test_pydantic_payload_with_unknown_source_blocks(self) -> None:
        """Test Pydantic agent outputs are inspected through model_dump()."""

        class AnswerPayload(BaseModel):
            text: str
            citations: list[dict[str, object]]

        registry = StaticSourceRegistry.from_iterable(["doc-001"])
        rule = CitationMembershipRule(registry=registry)
        payload = AnswerPayload(
            text="grounded claim",
            citations=[create_mock_citation(id="cite-fake", source_id="fake-doc").to_dict()],
        )

        result = await rule.check(payload)

        assert result.passed is False
        assert result.errors[0].value == "fake-doc"

    @pytest.mark.asyncio
    async def test_invalid_source_id_shape_blocks(self) -> None:
        """Test citation-shaped mappings with empty/non-string source_id are not accepted."""
        registry = StaticSourceRegistry.from_iterable(["doc-001"])
        rule = CitationMembershipRule(registry=registry)

        result = await rule.check({"id": "cite-empty", "source_id": "", "source_type": "document"})

        assert result.passed is False
        assert result.errors[0].value == ""

    @pytest.mark.asyncio
    async def test_no_citations_passes(self) -> None:
        """Test empty citation list passes trivially."""
        registry = StaticSourceRegistry.from_iterable(["doc-001"])
        rule = CitationMembershipRule(registry=registry)

        result = await rule.check([])

        assert result.passed is True
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_rule_name(self) -> None:
        """Test rule has a name."""
        registry = StaticSourceRegistry.from_iterable([])
        rule = CitationMembershipRule(registry=registry, name="membership")
        assert rule.name == "membership"


# =============================================================================
# CitationMembershipEvaluator Tests — bridges into GateEvalInterceptor
# =============================================================================


class TestCitationMembershipEvaluator:
    """Tests for CitationMembershipEvaluator."""

    @pytest.mark.asyncio
    async def test_known_source_scores_full_and_passes(self) -> None:
        """Test known source scores 1.0 and passes."""
        registry = StaticSourceRegistry.from_iterable(["doc-001"])
        evaluator = CitationMembershipEvaluator(registry=registry)
        citation = create_mock_citation(source_id="doc-001")

        result = await evaluator.evaluate(output=citation)

        assert result.score == 1.0
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_unknown_source_scores_zero_and_fails(self) -> None:
        """Test unknown source scores 0.0 and fails — this is the gate hook."""
        registry = StaticSourceRegistry.from_iterable(["doc-001"])
        evaluator = CitationMembershipEvaluator(registry=registry)
        citation = create_mock_citation(id="cite-fake", source_id="fabricated-source")

        result = await evaluator.evaluate(output=citation)

        assert result.score == 0.0
        assert result.passed is False
        assert "fabricated-source" in result.reason
