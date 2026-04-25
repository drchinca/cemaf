"""Temporal decay scoring for memory items."""

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from cemaf.core.utils import utc_now
from cemaf.memory.base import MemoryItem


class DecayFunction(StrEnum):
    """Decay curves for recency scoring."""

    EXPONENTIAL = "exponential"  # e^(-λt)
    LINEAR = "linear"  # max(0, 1 - t/max_age)
    LOGARITHMIC = "logarithmic"  # 1/(1 + log(1+t))


@dataclass(frozen=True)
class ScoringWeights:
    """Weights for combining scoring dimensions."""

    recency: float = 0.4
    confidence: float = 0.3
    frequency: float = 0.2
    relevance: float = 0.1

    def __post_init__(self) -> None:
        total = self.recency + self.confidence + self.frequency + self.relevance
        if not math.isclose(total, 1.0, abs_tol=1e-6):
            raise ValueError(f"Weights must sum to 1.0, got {total}")


@dataclass(frozen=True)
class ScoredMemoryItem:
    """A memory item annotated with scoring dimensions."""

    item: MemoryItem
    score: float
    recency_score: float
    confidence_score: float
    frequency_score: float
    relevance_score: float


@runtime_checkable
class MemoryScorer(Protocol):
    """Scores memory items for ranking and compaction decisions."""

    def score(
        self,
        item: MemoryItem,
        *,
        access_count: int = 0,
        relevance: float = 0.0,
    ) -> ScoredMemoryItem: ...

    def score_batch(
        self,
        items: tuple[MemoryItem, ...],
        *,
        access_counts: dict[str, int] | None = None,
    ) -> tuple[ScoredMemoryItem, ...]: ...


class TemporalDecayScorer:
    """Scores memory items using temporal decay and multi-dimensional weights."""

    def __init__(
        self,
        *,
        weights: ScoringWeights | None = None,
        decay_function: DecayFunction = DecayFunction.EXPONENTIAL,
        half_life_seconds: float = 3600.0,
        max_age_seconds: float = 86400.0,
        max_frequency: int = 100,
    ) -> None:
        self._weights = weights or ScoringWeights()
        self._decay_function = decay_function
        self._half_life_seconds = half_life_seconds
        self._max_age_seconds = max_age_seconds
        self._max_frequency = max_frequency
        # Pre-compute lambda for exponential decay: λ = ln(2) / half_life
        self._lambda = math.log(2) / self._half_life_seconds

    def _compute_recency(self, item: MemoryItem) -> float:
        """Compute recency score using configured decay function."""
        now = utc_now()
        age_seconds = max(0.0, (now - item.updated_at).total_seconds())

        if self._decay_function == DecayFunction.EXPONENTIAL:
            return math.exp(-self._lambda * age_seconds)
        elif self._decay_function == DecayFunction.LINEAR:
            return max(0.0, 1.0 - age_seconds / self._max_age_seconds)
        else:  # LOGARITHMIC
            return 1.0 / (1.0 + math.log(1.0 + age_seconds))

    def _compute_confidence(self, item: MemoryItem) -> float:
        """Normalize confidence to 0.0-1.0."""
        return max(0.0, min(1.0, float(item.confidence)))

    def _compute_frequency(self, access_count: int) -> float:
        """Normalize access frequency to 0.0-1.0."""
        if access_count <= 0:
            return 0.0
        return min(1.0, access_count / self._max_frequency)

    def score(
        self,
        item: MemoryItem,
        *,
        access_count: int = 0,
        relevance: float = 0.0,
    ) -> ScoredMemoryItem:
        """Score a single memory item across all dimensions."""
        recency = self._compute_recency(item=item)
        confidence = self._compute_confidence(item=item)
        frequency = self._compute_frequency(access_count=access_count)
        relevance_clamped = max(0.0, min(1.0, relevance))

        combined = (
            self._weights.recency * recency
            + self._weights.confidence * confidence
            + self._weights.frequency * frequency
            + self._weights.relevance * relevance_clamped
        )

        return ScoredMemoryItem(
            item=item,
            score=combined,
            recency_score=recency,
            confidence_score=confidence,
            frequency_score=frequency,
            relevance_score=relevance_clamped,
        )

    def score_batch(
        self,
        items: tuple[MemoryItem, ...],
        *,
        access_counts: dict[str, int] | None = None,
    ) -> tuple[ScoredMemoryItem, ...]:
        """Score multiple items, sorted by score descending."""
        counts = access_counts or {}
        scored = tuple(
            self.score(
                item=item,
                access_count=counts.get(item.full_key, 0),
            )
            for item in items
        )
        return tuple(sorted(scored, key=lambda s: s.score, reverse=True))
