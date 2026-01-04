"""
Citation models for tracking source attribution.

Provides:
- Citation: A source citation with metadata
- CitedFact: A factual claim with supporting citations
- CitationRegistry: Registry for tracking all citations in a run
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from cemaf.core.types import JSON


@dataclass(frozen=True)
class Citation:
    """
    A source citation with metadata.

    Represents a single source that backs a factual claim.
    """

    id: str
    source_id: str  # ID of source document/record
    source_type: str  # "document", "url", "database", "api"
    title: str = ""
    url: str | None = None
    author: str | None = None
    date: datetime | None = None
    page: int | None = None
    section: str | None = None
    quote: str = ""  # Exact quoted text
    confidence: float = 1.0  # 0.0-1.0 confidence in citation
    metadata: JSON = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "title": self.title,
            "url": self.url,
            "author": self.author,
            "date": self.date.isoformat() if self.date else None,
            "page": self.page,
            "section": self.section,
            "quote": self.quote,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Citation:
        """Create from dictionary."""
        date_value = data.get("date")
        if date_value is not None and isinstance(date_value, str):
            date_value = datetime.fromisoformat(date_value)

        return cls(
            id=data["id"],
            source_id=data["source_id"],
            source_type=data["source_type"],
            title=data.get("title", ""),
            url=data.get("url"),
            author=data.get("author"),
            date=date_value,
            page=data.get("page"),
            section=data.get("section"),
            quote=data.get("quote", ""),
            confidence=data.get("confidence", 1.0),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_search_result(cls, result: SearchResult, id_prefix: str = "cite") -> Citation:  # noqa: F821
        """
        Create citation from a SearchResult.

        Extracts metadata from SearchResult to populate citation fields.
        """
        # Generate unique ID
        citation_id = f"{id_prefix}_{uuid.uuid4().hex[:8]}"

        # Extract document info
        doc = result.document
        doc_metadata = doc.metadata

        # Extract title, url, author from metadata
        title = doc_metadata.get("title", "")
        url = doc_metadata.get("url")
        author = doc_metadata.get("author")

        # Handle date from metadata
        date_value = doc_metadata.get("date")
        if date_value is not None and isinstance(date_value, str):
            try:
                date_value = datetime.fromisoformat(date_value)
            except ValueError:
                date_value = None
        elif not isinstance(date_value, datetime):
            date_value = None

        # Extract page and section if available
        page = doc_metadata.get("page")
        if page is not None:
            try:
                page = int(page)
            except (ValueError, TypeError):
                page = None

        section = doc_metadata.get("section")

        # Determine source type from metadata or default
        source_type = doc_metadata.get("source_type", "document")

        # Use document content as the quote
        quote = doc.content

        # Confidence from search result score (normalize if needed)
        confidence = min(1.0, max(0.0, result.score))

        # Combine result metadata with additional info
        combined_metadata = {
            **result.metadata,
            "search_rank": result.rank,
            "search_score": result.score,
        }

        return cls(
            id=citation_id,
            source_id=doc.id,
            source_type=source_type,
            title=title,
            url=url,
            author=author,
            date=date_value,
            page=page,
            section=section,
            quote=quote,
            confidence=confidence,
            metadata=combined_metadata,
        )


@dataclass(frozen=True)
class CitedFact:
    """
    A factual claim with supporting citations.
    """

    id: str
    fact: str  # The factual statement
    citations: tuple[Citation, ...]  # Supporting citations
    confidence: float = 1.0  # Aggregated confidence
    verification_status: str = "unverified"  # "verified", "unverified", "disputed"

    @property
    def is_cited(self) -> bool:
        """Whether this fact has at least one citation."""
        return len(self.citations) > 0

    @property
    def primary_citation(self) -> Citation | None:
        """Get the primary (first) citation."""
        return self.citations[0] if self.citations else None

    @property
    def citation_count(self) -> int:
        """Number of citations."""
        return len(self.citations)


class CitationRegistry:
    """
    Registry for tracking all citations in a run.

    Mutable container for collecting citations during execution.
    """

    def __init__(self) -> None:
        self._citations: dict[str, Citation] = {}
        self._cited_facts: list[CitedFact] = []
        self._uncited_facts: list[str] = []

    def register(self, citation: Citation) -> None:
        """Register a citation."""
        self._citations[citation.id] = citation

    def register_many(self, citations: list[Citation]) -> None:
        """Register multiple citations."""
        for c in citations:
            self.register(c)

    def add_cited_fact(self, fact: CitedFact) -> None:
        """Add a cited fact."""
        self._cited_facts.append(fact)
        for c in fact.citations:
            self.register(c)

    def add_uncited_fact(self, fact: str) -> None:
        """Track an uncited fact."""
        self._uncited_facts.append(fact)

    def get_citation(self, id: str) -> Citation | None:
        """Get citation by ID."""
        return self._citations.get(id)

    def get_all_citations(self) -> tuple[Citation, ...]:
        """Get all registered citations."""
        return tuple(self._citations.values())

    def get_cited_facts(self) -> tuple[CitedFact, ...]:
        """Get all cited facts."""
        return tuple(self._cited_facts)

    def get_uncited_facts(self) -> tuple[str, ...]:
        """Get all uncited facts."""
        return tuple(self._uncited_facts)

    def get_citation_report(self) -> dict[str, Any]:
        """Generate a summary report of citations."""
        total_cited = len(self._cited_facts)
        total_uncited = len(self._uncited_facts)
        total_facts = total_cited + total_uncited

        return {
            "total_citations": len(self._citations),
            "total_cited_facts": total_cited,
            "total_uncited_facts": total_uncited,
            "citation_rate": total_cited / total_facts if total_facts > 0 else 1.0,
            "citations": [c.to_dict() for c in self._citations.values()],
        }

    def clear(self) -> None:
        """Clear all registered citations and facts."""
        self._citations.clear()
        self._cited_facts.clear()
        self._uncited_facts.clear()
