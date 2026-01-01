"""
Citation protocols - Abstract interfaces for citation tracking.

Supports:
- Citation tracking through retrieval/generation pipeline
- Source attribution and provenance
- Citation format validation
- Citation registry for run-level tracking

## Protocol-First Design

This module provides structural typing via @runtime_checkable protocols.
Any class that implements the required methods is automatically compatible.

Extension Point:
    Implement these protocols for custom citation tracking and storage.
    No registration needed - structural typing ensures compatibility.
"""

from typing import Protocol, runtime_checkable

# Re-export data classes (not changed)
from cemaf.citation.models import Citation, CitationRegistry, CitedFact

__all__ = [
    "CitationTracker",
    # Data classes
    "Citation",
    "CitedFact",
    "CitationRegistry",
]


@runtime_checkable
class CitationTracker(Protocol):
    """
    Protocol for citation tracker implementations.

    A CitationTracker manages citations throughout execution:
    - Add citations from retrieved documents
    - Track cited facts with supporting citations
    - Validate citation format and completeness
    - Generate citation reports

    Extension Point:
        - Simple tracker (in-memory list)
        - Persistent tracker (database)
        - Distributed tracker (shared across runs)
        - Format-aware tracker (APA, MLA, Chicago, IEEE)
        - Validated tracker (ensures all facts have citations)

    Example:
        >>> class SimpleCitationTracker:
        ...     def __init__(self):
        ...         self._citations = []
        ...
        ...     async def add_citation(self, citation: Citation) -> None:
        ...         self._citations.append(citation)
        ...
        ...     async def get_all_citations(self) -> list[Citation]:
        ...         return self._citations.copy()
        ...
        ...     async def add_cited_fact(self, fact: CitedFact) -> None:
        ...         for citation in fact.citations:
        ...             await self.add_citation(citation)
        >>>
        >>> tracker = SimpleCitationTracker()
        >>> assert isinstance(tracker, CitationTracker)
    """

    async def add_citation(self, citation: Citation) -> None:
        """
        Add a citation to the tracker.

        Args:
            citation: Citation instance to track

        Example:
            >>> citation = Citation(
            ...     source_id="doc-123",
            ...     title="Example Paper",
            ...     url="https://example.com/paper.pdf"
            ... )
            >>> await tracker.add_citation(citation)
        """
        ...

    async def add_cited_fact(self, fact: CitedFact) -> None:
        """
        Add a cited fact with its supporting citations.

        Args:
            fact: CitedFact instance with claim and citations

        Example:
            >>> fact = CitedFact(
            ...     claim="The sky is blue",
            ...     citations=[citation1, citation2]
            ... )
            >>> await tracker.add_cited_fact(fact)
        """
        ...

    async def get_all_citations(self) -> list[Citation]:
        """
        Get all citations tracked in this run.

        Returns:
            List of all citations

        Example:
            >>> citations = await tracker.get_all_citations()
            >>> for citation in citations:
            ...     print(f"[{citation.source_id}] {citation.title}")
        """
        ...
