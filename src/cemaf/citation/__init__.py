"""
Citation module for tracking source attribution.

Provides:
- Citation: A source citation with metadata
- CitedFact: A factual claim with supporting citations
- CitationRegistry: Registry for tracking all citations in a run
- CitationTracker: Tracks citations through the retrieval/generation pipeline
"""

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
from cemaf.citation.rules import CitationFormatRule, CitationRequiredRule
from cemaf.citation.tracker import CitationTracker

__all__ = [
    # Models
    "Citation",
    "CitedFact",
    "CitationRegistry",
    # Tracker
    "CitationTracker",
    "create_citation_tracker",
    "create_citation_tracker_from_config",
    "citation_tracker_registry",
    # Validation rules
    "CitationFormatRule",
    "CitationRequiredRule",
    # Mocks for testing
    "MockCitationTracker",
    "create_mock_citation",
    "create_mock_cited_fact",
]
