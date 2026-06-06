"""Auction-based agent selection (SPEC-09).

Opt-in capability/load/budget-aware selection among competing agents. The static
`ref_id` path stays the default; this engages only when a node declares a
`Capability` and an `AgentSelector` is wired. Scoring is a pure, deterministic
function of its inputs — runs stay replayable and choices auditable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from cemaf.agents.protocols import Agent
from cemaf.core.types import JSON, AgentID

_DEFAULT_LOAD = 0.5
_DEFAULT_MATCH = 0.3
_FULL_MATCH = 1.0

# Scoring weights (sum to 1.0).
_W_MATCH = 0.5
_W_LOAD = 0.3
_W_BUDGET = 0.2


class Capability(StrEnum):
    RESEARCH = "research"
    SUMMARIZE = "summarize"
    WRITE = "write"
    LIBRARY = "library"
    QUALITY = "quality"


class Fidelity(StrEnum):
    LOW = "low"
    STANDARD = "standard"
    HIGH = "high"


# Applied in model_router (SPEC-09 Invariant 9); colocated with Capability.
FIDELITY_FLOOR: dict[Fidelity, float] = {
    Fidelity.LOW: 0.0,
    Fidelity.STANDARD: 0.4,
    Fidelity.HIGH: 0.8,
}


@dataclass(frozen=True, slots=True)
class BidContext:
    capability: Capability
    goal_text: str = ""
    cost_utilization: float = 0.0
    token_utilization: float = 0.0


@dataclass(frozen=True, slots=True)
class Bid:
    agent_id: AgentID
    score: float
    capability_match: float
    load_factor: float
    budget_headroom: float

    def to_metadata(self) -> JSON:
        """Provenance projection stored on NodeResult.metadata['selection']."""
        return {
            "agent_id": str(self.agent_id),
            "score": self.score,
            "capability_match": self.capability_match,
            "load_factor": self.load_factor,
            "budget_headroom": self.budget_headroom,
        }


@runtime_checkable
class CapabilityAdvertiser(Protocol):
    """OPTIONAL protocol an Agent MAY implement. Non-advertisers get default scoring."""

    @property
    def capabilities(self) -> frozenset[Capability]: ...

    @property
    def current_load(self) -> float: ...


@runtime_checkable
class AgentSelector(Protocol):
    """BYO-X seam — swap the scoring policy. DefaultAgentSelector is the default."""

    def select(
        self,
        *,
        candidates: tuple[Agent[Any, Any], ...],
        bid_context: BidContext,
    ) -> Bid | None: ...


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def read_capabilities(agent: Agent[Any, Any]) -> frozenset[Capability] | None:
    """Duck-typed read — isinstance on a @runtime_checkable Protocol can't verify return types."""
    raw = getattr(agent, "capabilities", None)
    if not isinstance(raw, frozenset):
        return None
    return frozenset(c for c in raw if isinstance(c, Capability))


def read_load(agent: Agent[Any, Any]) -> float:
    """Self-reported, untrusted — default 0.5 when absent/malformed, clamped to [0,1]."""
    raw = getattr(agent, "current_load", None)
    if not isinstance(raw, int | float) or isinstance(raw, bool):
        return _DEFAULT_LOAD
    return _clamp(float(raw))


class DefaultAgentSelector:
    """Deterministic single-round max-bid selector."""

    def bid_for(self, *, agent: Agent[Any, Any], bid_context: BidContext) -> Bid:
        caps = read_capabilities(agent)
        match = _FULL_MATCH if caps is not None and bid_context.capability in caps else _DEFAULT_MATCH
        load_factor = _clamp(1.0 - read_load(agent))
        budget_headroom = _clamp(
            1.0 - max(_clamp(bid_context.cost_utilization), _clamp(bid_context.token_utilization))
        )
        score = _clamp(_W_MATCH * match + _W_LOAD * load_factor + _W_BUDGET * budget_headroom)
        return Bid(
            agent_id=agent.id,
            score=score,
            capability_match=match,
            load_factor=load_factor,
            budget_headroom=budget_headroom,
        )

    def select(self, *, candidates: tuple[Agent[Any, Any], ...], bid_context: BidContext) -> Bid | None:
        if not candidates:
            return None
        bids = [self.bid_for(agent=agent, bid_context=bid_context) for agent in candidates]
        # Newest-first by (score, id) — id tie-break gives a unique, stable winner.
        bids.sort(key=lambda b: (b.score, str(b.agent_id)), reverse=True)
        return bids[0]


def create_default_agent_selector() -> DefaultAgentSelector:
    """Factory (BYO-X) — wired into RuntimeServices.agent_selector at bootstrap."""
    return DefaultAgentSelector()
