"""Decision types for the interceptor spine (SPEC-01a §2).

Names align with the full SPEC-01 (`PreflightDecision`/`PostflightDecision`, one
`DecisionKind` superset) so the richer spec extends rather than renames.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from cemaf.agents.base import AgentContext
from cemaf.core.types import JSON


class DecisionKind(StrEnum):
    ACCEPT = "accept"  # proceed (PRE: run agent / POST: keep result)
    REJECT = "reject"  # short-circuit (PRE: skip agent / POST: fail the node)
    # RECOVER / HALT are added by full SPEC-01; this slice handles ACCEPT/REJECT only.


@dataclass(frozen=True, slots=True)
class PreflightDecision:
    """Outcome of one PRE interceptor.

    On ACCEPT, `enriched_context` (if set) replaces the context seen by the next
    interceptor and the agent — built via `AgentContext.model_copy(update=...)`.
    None means "use prior context unchanged".
    """

    kind: DecisionKind
    interceptor_id: str
    enriched_context: AgentContext | None = None
    reason: str | None = None  # required (non-empty) when REJECT

    def __post_init__(self) -> None:
        if self.kind is DecisionKind.REJECT and not (self.reason and self.reason.strip()):
            raise ValueError("PreflightDecision REJECT requires a non-empty reason")


@dataclass(frozen=True, slots=True)
class PostflightDecision:
    """Outcome of one POST interceptor.

    On ACCEPT, `metadata` (if set) is merged under
    `NodeResult.metadata["interceptors"][interceptor_id]` for provenance.
    """

    kind: DecisionKind
    interceptor_id: str
    reason: str | None = None  # required (non-empty) when REJECT
    metadata: JSON | None = None

    def __post_init__(self) -> None:
        if self.kind is DecisionKind.REJECT and not (self.reason and self.reason.strip()):
            raise ValueError("PostflightDecision REJECT requires a non-empty reason")
