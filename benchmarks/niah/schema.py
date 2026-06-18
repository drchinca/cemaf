"""Typed results schema for the SPEC-11 needle-in-haystack benchmark.

Frozen dataclasses + enums (CEMAF house style — no bare dict/list, no plain strings for
identifiers). Every other module in `benchmarks/niah/` imports from here; this is the
load-bearing contract per SPEC-11 §2.1.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Arm(Enum):
    """The three benchmark arms (SPEC-11 §1)."""

    CEMAF_FULL = "cemaf_full"  # vector + KG + compactor + priority compiler
    CEMAF_NO_KG = "cemaf_no_kg"  # ablation: full stack with KG hop-traversal disabled
    NAIVE_DUMP = "naive_dump"  # baseline: top-k concat to window, truncate beyond


@dataclass(frozen=True, slots=True)
class HaystackTier:
    """One scale point on the curve."""

    label: str  # human-readable: "10MB", "100MB", "1GB"
    size_bytes: int
    doc_count: int


@dataclass(frozen=True, slots=True)
class HotpotQuestion:
    """One labeled HotpotQA question; gold supporting passages must be in any haystack."""

    question_id: str
    question: str
    gold_answer: str
    gold_supporting_passages: tuple[str, ...]
    is_multi_hop: bool


@dataclass(frozen=True, slots=True)
class Document:
    """A retrievable unit in the haystack — a Wikipedia-style title + text body."""

    doc_id: str
    title: str
    text: str

    @property
    def size_bytes(self) -> int:
        return len(self.text.encode("utf-8"))


@dataclass(frozen=True, slots=True)
class QuestionRun:
    """Result of one (arm, question, tier, rep) run. SPEC-11 §2.1 contract."""

    question_id: str
    arm: Arm
    tier: HaystackTier
    rep: int
    compiled_tokens: int  # bytes the LLM actually saw (after compile)
    compile_ms: int  # retrieval + compaction wall time
    answer_ms: int  # answering LLM call wall time
    cost_usd: float
    answer_text: str
    judged_correct: bool  # judge says answer matches gold
    citation_grounded: bool  # answer's claims trace to compiled context
    error: str | None = None  # populated on failure; the run is NEVER silently dropped


@dataclass(frozen=True, slots=True)
class ArmAggregate:
    """Per (arm, tier) rollup across all questions and reps."""

    arm: Arm
    tier: HaystackTier
    n: int
    correctness_rate: float  # mean(judged_correct AND citation_grounded) — the headline
    correctness_stderr: float
    p50_compile_ms: int
    p50_answer_ms: int
    mean_cost_usd: float


@dataclass(frozen=True, slots=True)
class ScalingCurve:
    """One arm's scaling curve — points ordered by tier.size_bytes ascending."""

    arm: Arm
    points: tuple[ArmAggregate, ...]


def headline_metric(*, run: QuestionRun) -> bool:
    """SPEC-11 §3 Invariant 4: headline counts correct AND citation-grounded.

    A judge-correct answer that does not trace back to the compiled context fails the gate;
    this defends against memorized-answer false positives inflating any arm.
    """
    return run.judged_correct and run.citation_grounded
