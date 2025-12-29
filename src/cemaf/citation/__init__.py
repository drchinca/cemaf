"""
Citation module for tracking source attribution.

Provides:
- Citation: A source citation with metadata
- CitedFact: A factual claim with supporting citations
- CitationRegistry: Registry for tracking all citations in a run
- CitationTracker: Tracks citations through the retrieval/generation pipeline
"""

from cemaf.citation.models import Citation, CitedFact, CitationRegistry
from cemaf.citation.tracker import CitationTracker
from cemaf.citation.rules import CitationFormatRule, CitationRequiredRule
from cemaf.citation.mock import (
    MockCitationTracker,
    create_mock_citation,
    create_mock_cited_fact,
)

__all__ = [
    # Models
    "Citation",
    "CitedFact",
    "CitationRegistry",
    # Tracker
    "CitationTracker",
    # Validation rules
    "CitationFormatRule",
    "CitationRequiredRule",
    # Mocks for testing
    "MockCitationTracker",
    "create_mock_citation",
    "create_mock_cited_fact",
]
