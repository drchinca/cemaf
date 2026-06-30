"""Types for the agent council (SPEC-10 §2)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from cemaf.core.types import JSON, AgentID


def _clamp_confidence(value: float) -> float:
    """Clamp to [0,1]; NaN/inf → 0.0 (never let a bad weight corrupt a tally)."""
    if not math.isfinite(value):
        return 0.0
    return min(1.0, max(0.0, value))


class AggregationMethod(StrEnum):
    MAJORITY = "majority"
    WEIGHTED = "weighted"
    QUORUM = "quorum"
    UNANIMOUS = "unanimous"


@dataclass(frozen=True, slots=True)
class CouncilQuestion:
    """The closed decision: a prompt and the enumerated options members vote among."""

    prompt: str
    options: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.options) < 2:
            raise ValueError("CouncilQuestion needs >= 2 options")
        if len(set(self.options)) != len(self.options):
            raise ValueError("CouncilQuestion options must be unique")


@dataclass(frozen=True, slots=True)
class Opinion:
    """One member's vote. `choice` MUST be in the question's options unless abstained."""

    member_id: AgentID
    choice: str | None
    confidence: float = 1.0
    rationale: str = ""
    abstained: bool = False
    raw_choice: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "confidence", _clamp_confidence(self.confidence))


@dataclass(frozen=True, slots=True)
class Ballot:
    """Provenance record of one member's participation."""

    member_id: AgentID
    choice: str | None
    confidence: float
    abstained: bool
    error: str | None = None
    raw_choice: str | None = None
    rationale: str = ""  # member's own reason for the vote (from Opinion.rationale)

    def to_dict(self) -> JSON:
        return {
            "member_id": str(self.member_id),
            "choice": self.choice,
            "confidence": self.confidence,
            "abstained": self.abstained,
            "error": self.error,
            "raw_choice": self.raw_choice,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class CouncilDecision:
    winning_choice: str | None
    method: AggregationMethod
    tally: dict[str, float]
    ballots: tuple[Ballot, ...]
    quorum_met: bool

    @property
    def decided(self) -> bool:
        return self.winning_choice is not None

    def to_metadata(self) -> JSON:
        return {
            "winning_choice": self.winning_choice,
            "method": self.method.value,
            "decided": self.decided,
            "quorum_met": self.quorum_met,
            "tally": dict(self.tally),
            "ballots": [b.to_dict() for b in self.ballots],
        }


@dataclass(frozen=True, slots=True)
class CouncilConfig:
    method: AggregationMethod = AggregationMethod.MAJORITY
    quorum_fraction: float = 0.5
    min_members: int = 1
    member_timeout: timedelta = timedelta(seconds=30)
    max_concurrency: int = 8
    # Multi-round deliberation: rounds > 1 means after round 1 the executor
    # injects each member's prior-round opinions (rationale included) under
    # ``AgentContext.global_memory["council_prior_round"]``. Members that read
    # that key see peers' votes and may revise theirs; members that ignore it
    # remain a parallel ensemble. Early-stops when a round's tally matches the
    # prior round's (no point burning cost on a settled vote). Default 1 keeps
    # existing single-round behaviour byte-identical.
    rounds: int = 1

    def __post_init__(self) -> None:
        if not (0.0 < self.quorum_fraction <= 1.0):
            raise ValueError("quorum_fraction must be in (0, 1]")
        if self.min_members < 1:
            raise ValueError("min_members must be >= 1")
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        if self.rounds < 1:
            raise ValueError("rounds must be >= 1")
