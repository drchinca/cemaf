"""
Citation tracker for the retrieval and generation pipeline.

Provides:
- CitationTracker: Tracks citations through the pipeline
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from cemaf.citation.models import Citation, CitationRegistry, CitedFact


class CitationTracker:
    """
    Tracks citations through the retrieval and generation pipeline.

    Works with SearchResult metadata from the retrieval system to
    automatically create citations for retrieved content.

    Example:
        >>> tracker = CitationTracker()
        >>> citation = tracker.track_search_result(result)
        >>> cited_fact = tracker.create_cited_fact("The sky is blue", [citation])
        >>> report = tracker.get_citation_report()
    """

    def __init__(
        self,
        registry: CitationRegistry | None = None,
        event_bus: EventBus | None = None,  # noqa: F821
    ) -> None:
        """
        Initialize the citation tracker.

        Args:
            registry: Optional CitationRegistry to use. If not provided,
                     a new registry is created.
            event_bus: Optional EventBus for emitting citation events.
        """
        self._registry = registry or CitationRegistry()
        self._event_bus = event_bus

    @property
    def registry(self) -> CitationRegistry:
        """Get the citation registry."""
        return self._registry

    def track_search_result(self, result: SearchResult) -> Citation:  # noqa: F821
        """
        Convert a single SearchResult to a tracked Citation.

        Args:
            result: SearchResult  # noqa: F821 from retrieval

        Returns:
            Created Citation
        """
        citation = Citation.from_search_result(result)
        self._registry.register(citation)
        self._emit_event("citation.added", {"citation_id": citation.id})
        return citation

    def track_search_results(self, results: list[SearchResult]) -> list[Citation]:  # noqa: F821
        """
        Convert multiple SearchResults to tracked Citations.

        Args:
            results: List of SearchResults from retrieval

        Returns:
            List of created Citations
        """
        citations = []
        for result in results:
            citation = self.track_search_result(result)
            citations.append(citation)
        return citations

    def create_cited_fact(
        self,
        fact: str,
        citations: list[Citation],
        confidence: float = 1.0,
        verification_status: str = "unverified",
    ) -> CitedFact:
        """
        Create a cited fact and register it.

        Args:
            fact: The factual statement
            citations: List of supporting citations
            confidence: Confidence score (0.0-1.0)
            verification_status: Status of verification ("verified", "unverified", "disputed")

        Returns:
            Created CitedFact
        """
        cited_fact = CitedFact(
            id=f"fact-{uuid.uuid4().hex[:8]}",
            fact=fact,
            citations=tuple(citations),
            confidence=confidence,
            verification_status=verification_status,
        )
        self._registry.add_cited_fact(cited_fact)
        self._emit_event(
            "citation.fact_created",
            {
                "fact_id": cited_fact.id,
                "citation_count": cited_fact.citation_count,
            },
        )
        return cited_fact

    def record_uncited_fact(self, fact: str) -> None:
        """
        Record a fact that lacks citations.

        Emits a warning event but does NOT block.

        Args:
            fact: The uncited fact text
        """
        self._registry.add_uncited_fact(fact)
        self._emit_event("citation.missing", {"fact": fact})

    def get_citation(self, citation_id: str) -> Citation | None:
        """
        Get a citation by ID.

        Args:
            citation_id: The citation ID

        Returns:
            Citation if found, None otherwise
        """
        return self._registry.get_citation(citation_id)

    def get_all_citations(self) -> tuple[Citation, ...]:
        """
        Get all registered citations.

        Returns:
            Tuple of all citations
        """
        return self._registry.get_all_citations()

    def get_cited_facts(self) -> tuple[CitedFact, ...]:
        """
        Get all cited facts.

        Returns:
            Tuple of all cited facts
        """
        return self._registry.get_cited_facts()

    def get_uncited_facts(self) -> tuple[str, ...]:
        """
        Get all uncited facts.

        Returns:
            Tuple of uncited fact strings
        """
        return self._registry.get_uncited_facts()

    def get_citation_report(self) -> dict[str, Any]:
        """
        Generate citation report from registry.

        Returns:
            Dictionary with citation statistics and details
        """
        return self._registry.get_citation_report()

    def clear(self) -> None:
        """Clear all tracked citations and facts."""
        self._registry.clear()
        self._emit_event("citation.cleared", {})

    def _emit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """
        Emit event if event_bus is configured.

        Args:
            event_type: Type of event (e.g., "citation.added")
            payload: Event payload data
        """
        if self._event_bus is not None:
            from cemaf.events.protocols import Event

            event = Event.create(
                type=event_type,
                payload=payload,
                source="citation_tracker",
            )
            # Handle async publish in sync context
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._event_bus.publish(event))
            except RuntimeError:
                # No running loop, skip event emission
                pass
