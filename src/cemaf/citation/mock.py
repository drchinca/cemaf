"""Mock implementations for citation testing."""

from cemaf.citation.models import Citation, CitationRegistry, CitedFact
from cemaf.citation.tracker import CitationTracker


def create_mock_citation(
    id: str = "cite-001",
    source_id: str = "doc-001",
    source_type: str = "document",
    title: str = "Mock Source",
    **kwargs,
) -> Citation:
    """Create a mock citation for testing."""
    return Citation(
        id=id,
        source_id=source_id,
        source_type=source_type,
        title=title,
        **kwargs,
    )


def create_mock_cited_fact(
    fact: str = "This is a test fact.",
    citations: list[Citation] | None = None,
    **kwargs,
) -> CitedFact:
    """Create a mock cited fact for testing."""
    if citations is None:
        citations = [create_mock_citation()]
    return CitedFact(
        id=kwargs.pop("id", "fact-001"),
        fact=fact,
        citations=tuple(citations),
        **kwargs,
    )


class MockCitationTracker(CitationTracker):
    """Mock citation tracker that doesn't emit events."""

    def __init__(self) -> None:
        super().__init__(registry=CitationRegistry(), event_bus=None)
