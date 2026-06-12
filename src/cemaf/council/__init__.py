"""Agent council (SPEC-10) — deliberative multi-agent decisions.

N agents each produce an `Opinion` on a `CouncilQuestion`; a pluggable
`VoteAggregator` (majority/weighted/quorum/unanimous) combines them into a
`CouncilDecision` with per-member ballot provenance. Members run concurrently;
a failed or hung member abstains rather than crashing the council. Aggregation
is a pure, deterministic function of the opinion set.
"""

from cemaf.council.aggregator import DefaultVoteAggregator
from cemaf.council.council import AgentCouncil, create_agent_council
from cemaf.council.protocols import CouncilMember, VoteAggregator
from cemaf.council.types import (
    AggregationMethod,
    Ballot,
    CouncilConfig,
    CouncilDecision,
    CouncilQuestion,
    Opinion,
)

__all__ = [
    "AgentCouncil",
    "AggregationMethod",
    "Ballot",
    "CouncilConfig",
    "CouncilDecision",
    "CouncilMember",
    "CouncilQuestion",
    "DefaultVoteAggregator",
    "Opinion",
    "VoteAggregator",
    "create_agent_council",
]
