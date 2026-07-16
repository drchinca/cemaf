"""DataSource domain models — SPEC-02 adapted to landed types.

SPEC-02 (docs/specs/SPEC-02-kg-and-datasource-services.md) specifies these
types against SPEC-00 §2 common types (TokenBudget with a `pull_tokens`
field, a Citation shape distinct from citation/models.py, a shared
EntityRef/Goal) that are not ported into this codebase. This module:
  - defines EntityRef and CiteableChunk fresh — neither exists elsewhere
  - embeds cemaf.citation.models.Citation (the one real implementation)
    inside CiteableChunk instead of SPEC-00's incompatible Citation shape
  - uses cemaf.context.budget.TokenBudget (the landed dataclass) for the
    `budget` parameter to DataSource.retrieve(); it has no `pull_tokens`
    field, so PullInterceptor tracks its own token cap via constructor
    config rather than reading node.budget.pull_tokens (Node has no
    `budget` field either)
See docs/architecture/roadmap-plan.md Phase 5 for the SPEC-00 alignment gap.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final

from cemaf.citation.models import Citation
from cemaf.core.utils import utc_now


class DataSourceCapability(StrEnum):
    """What a DataSource can be asked to do."""

    READ = "read"
    SEARCH = "search"
    RELATIONS = "relations"


class HealthStatus(StrEnum):
    """Liveness state a DataSource reports via health()."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True, slots=True)
class EntityRef:
    """A typed reference to a business entity surfaced by extraction or the KG."""

    id: str
    label: str
    entity_type: str = ""


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    """One retrieval request PullInterceptor issues to a DataSource."""

    text: str
    entities: tuple[EntityRef, ...] = ()
    filters: Mapping[str, str] = field(default_factory=dict)
    top_k: int = 8
    timeout_ms: int = 3_000


# Sort-key band per originating layer — PullInterceptor's merge+eviction step
# sorts by (priority desc, confidence desc, retrieved_at asc) per SPEC-02 Inv 11.
PRIORITY_BY_SOURCE_KIND: Final[Mapping[str, int]] = {
    "kg": 100,
    "datasource": 80,
    "memory": 60,
    "vector": 40,
}

_SOURCE_KINDS: Final[frozenset[str]] = frozenset(PRIORITY_BY_SOURCE_KIND)
_TENANT_OFFSET_BOUND: Final[int] = 10


@dataclass(frozen=True, slots=True)
class CiteableChunk:
    """One unit of retrieved, citeable context (SPEC-02 §2).

    `citation` is the real `cemaf.citation.models.Citation` — it has no field
    literally named `locator`; a chunk's "locator" is whichever of
    `url`/`context_path`/`section`/`page` the citation carries.
    """

    chunk_id: str
    content: str
    citation: Citation
    token_count: int
    source_kind: str
    confidence: float = 1.0
    tenant_offset: int = 0
    retrieved_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.source_kind not in _SOURCE_KINDS:
            raise ValueError(f"source_kind must be one of {sorted(_SOURCE_KINDS)}, got {self.source_kind!r}")
        if not self.citation.source_id:
            raise ValueError("CiteableChunk citation missing source_id")
        locator = (self.citation.url, self.citation.context_path, self.citation.section, self.citation.page)
        if not any(locator):
            raise ValueError("CiteableChunk citation missing a locator (url/context_path/section/page)")
        if not (-_TENANT_OFFSET_BOUND <= self.tenant_offset <= _TENANT_OFFSET_BOUND):
            raise ValueError(
                f"tenant_offset must be within ±{_TENANT_OFFSET_BOUND}, got {self.tenant_offset}"
            )

    @property
    def priority(self) -> int:
        """Pure band value for the originating source_kind (testable independent of tenant_offset)."""
        return PRIORITY_BY_SOURCE_KIND[self.source_kind]

    @property
    def effective_priority(self) -> int:
        """The actual eviction sort key — priority band plus tenant offset."""
        return self.priority + self.tenant_offset
