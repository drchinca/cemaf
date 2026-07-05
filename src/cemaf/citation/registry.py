"""Source registry — the allowed-source membership port for citation enforcement.

Citations can be tracked and warned about (CitationRequiredRule,
CitationFormatRule) without ever confirming the cited source actually exists.
SourceRegistry closes that gap: it answers "is this source_id real?" against
whatever backs the allow-list — an in-memory set today, an ontology service
or database tomorrow.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class SourceRegistry(Protocol):
    """Port for checking whether a source_id is a known, citable source.

    Extension Point:
        - StaticSourceRegistry (below): fixed in-memory allow-list
        - Database-backed registry: query an ontology/catalog table
        - API-backed registry: call an external source-of-truth service
    """

    def is_known(self, source_id: str) -> bool:
        """Return True if source_id is a recognized, citable source."""
        ...


@dataclass(frozen=True)
class StaticSourceRegistry:
    """In-memory allow-list of known source IDs.

    Default SourceRegistry implementation — fits small, fixed ontologies
    (dozens to low thousands of entries) with no external lookup needed.
    """

    allowed_source_ids: frozenset[str]

    @classmethod
    def from_iterable(cls, source_ids: Iterable[str]) -> StaticSourceRegistry:
        """Build a registry from any iterable of source IDs."""
        return cls(allowed_source_ids=frozenset(source_ids))

    def is_known(self, source_id: str) -> bool:
        """Return True if source_id is in the allow-list."""
        return source_id in self.allowed_source_ids
