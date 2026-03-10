"""Tests for temporal decay scoring."""

import math
from datetime import timedelta

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.core.types import Confidence
from cemaf.core.utils import utc_now
from cemaf.memory.base import MemoryItem
from cemaf.memory.scoring import (
    DecayFunction,
    MemoryScorer,
    ScoredMemoryItem,
    ScoringWeights,
    TemporalDecayScorer,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_item(
    *,
    key: str = "test",
    age_seconds: float = 0.0,
    confidence: float = 1.0,
) -> MemoryItem:
    """Create a MemoryItem with a specific age."""
    now = utc_now()
    created = now - timedelta(seconds=age_seconds)
    return MemoryItem(
        scope=MemoryScope.SESSION,
        key=key,
        value={"data": key},
        confidence=Confidence(confidence),
        created_at=created,
        updated_at=created,
    )


# ---------------------------------------------------------------------------
# ScoringWeights
# ---------------------------------------------------------------------------


class TestScoringWeights:
    def test_default_weights_sum_to_one(self) -> None:
        weights = ScoringWeights()
        total = weights.recency + weights.confidence + weights.frequency + weights.relevance
        assert math.isclose(total, 1.0)

    def test_custom_weights_valid(self) -> None:
        weights = ScoringWeights(recency=0.5, confidence=0.2, frequency=0.2, relevance=0.1)
        assert weights.recency == 0.5

    def test_weights_must_sum_to_one(self) -> None:
        with pytest.raises(ValueError, match="sum to 1.0"):
            ScoringWeights(recency=0.5, confidence=0.5, frequency=0.5, relevance=0.5)

    def test_weights_are_frozen(self) -> None:
        weights = ScoringWeights()
        with pytest.raises(AttributeError):
            weights.recency = 0.9  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ScoredMemoryItem
# ---------------------------------------------------------------------------


class TestScoredMemoryItem:
    def test_preserves_original_item(self) -> None:
        item = _make_item()
        scored = ScoredMemoryItem(
            item=item,
            score=0.8,
            recency_score=0.9,
            confidence_score=1.0,
            frequency_score=0.0,
            relevance_score=0.0,
        )
        assert scored.item is item
        assert scored.score == 0.8

    def test_is_frozen(self) -> None:
        scored = ScoredMemoryItem(
            item=_make_item(),
            score=0.5,
            recency_score=0.5,
            confidence_score=0.5,
            frequency_score=0.0,
            relevance_score=0.0,
        )
        with pytest.raises(AttributeError):
            scored.score = 0.9  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TemporalDecayScorer — protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_implements_memory_scorer(self) -> None:
        scorer = TemporalDecayScorer()
        assert isinstance(scorer, MemoryScorer)


# ---------------------------------------------------------------------------
# Exponential decay
# ---------------------------------------------------------------------------


class TestExponentialDecay:
    def test_fresh_item_has_high_recency(self) -> None:
        scorer = TemporalDecayScorer(decay_function=DecayFunction.EXPONENTIAL)
        item = _make_item(age_seconds=0.0)
        scored = scorer.score(item=item)
        assert scored.recency_score > 0.95

    def test_old_item_has_low_recency(self) -> None:
        scorer = TemporalDecayScorer(
            decay_function=DecayFunction.EXPONENTIAL,
            half_life_seconds=3600.0,
        )
        item = _make_item(age_seconds=36000.0)  # 10 half-lives
        scored = scorer.score(item=item)
        assert scored.recency_score < 0.01

    def test_half_life_halves_score(self) -> None:
        half_life = 3600.0
        scorer = TemporalDecayScorer(
            decay_function=DecayFunction.EXPONENTIAL,
            half_life_seconds=half_life,
        )
        item = _make_item(age_seconds=half_life)
        scored = scorer.score(item=item)
        # After one half-life, recency ≈ 0.5
        assert 0.45 < scored.recency_score < 0.55


# ---------------------------------------------------------------------------
# Linear decay
# ---------------------------------------------------------------------------


class TestLinearDecay:
    def test_fresh_item(self) -> None:
        scorer = TemporalDecayScorer(
            decay_function=DecayFunction.LINEAR,
            max_age_seconds=1000.0,
        )
        item = _make_item(age_seconds=0.0)
        scored = scorer.score(item=item)
        assert scored.recency_score > 0.99

    def test_midpoint(self) -> None:
        scorer = TemporalDecayScorer(
            decay_function=DecayFunction.LINEAR,
            max_age_seconds=1000.0,
        )
        item = _make_item(age_seconds=500.0)
        scored = scorer.score(item=item)
        assert 0.45 < scored.recency_score < 0.55

    def test_beyond_max_age_is_zero(self) -> None:
        scorer = TemporalDecayScorer(
            decay_function=DecayFunction.LINEAR,
            max_age_seconds=1000.0,
        )
        item = _make_item(age_seconds=2000.0)
        scored = scorer.score(item=item)
        assert scored.recency_score == 0.0


# ---------------------------------------------------------------------------
# Logarithmic decay
# ---------------------------------------------------------------------------


class TestLogarithmicDecay:
    def test_fresh_item(self) -> None:
        scorer = TemporalDecayScorer(decay_function=DecayFunction.LOGARITHMIC)
        item = _make_item(age_seconds=0.0)
        scored = scorer.score(item=item)
        assert scored.recency_score > 0.99

    def test_decays_slowly(self) -> None:
        scorer = TemporalDecayScorer(decay_function=DecayFunction.LOGARITHMIC)
        item = _make_item(age_seconds=3600.0)
        scored = scorer.score(item=item)
        # Logarithmic decay is much slower than exponential
        assert scored.recency_score > 0.1


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------


class TestConfidenceScoring:
    def test_high_confidence(self) -> None:
        scorer = TemporalDecayScorer()
        item = _make_item(confidence=1.0)
        scored = scorer.score(item=item)
        assert scored.confidence_score == 1.0

    def test_low_confidence(self) -> None:
        scorer = TemporalDecayScorer()
        item = _make_item(confidence=0.3)
        scored = scorer.score(item=item)
        assert scored.confidence_score == 0.3

    def test_clamps_above_one(self) -> None:
        scorer = TemporalDecayScorer()
        item = _make_item(confidence=1.5)
        scored = scorer.score(item=item)
        assert scored.confidence_score == 1.0


# ---------------------------------------------------------------------------
# Frequency scoring
# ---------------------------------------------------------------------------


class TestFrequencyScoring:
    def test_zero_access(self) -> None:
        scorer = TemporalDecayScorer()
        item = _make_item()
        scored = scorer.score(item=item, access_count=0)
        assert scored.frequency_score == 0.0

    def test_moderate_access(self) -> None:
        scorer = TemporalDecayScorer(max_frequency=100)
        item = _make_item()
        scored = scorer.score(item=item, access_count=50)
        assert scored.frequency_score == 0.5

    def test_capped_at_one(self) -> None:
        scorer = TemporalDecayScorer(max_frequency=100)
        item = _make_item()
        scored = scorer.score(item=item, access_count=200)
        assert scored.frequency_score == 1.0


# ---------------------------------------------------------------------------
# Combined score
# ---------------------------------------------------------------------------


class TestCombinedScore:
    def test_combined_is_weighted_sum(self) -> None:
        weights = ScoringWeights(recency=0.4, confidence=0.3, frequency=0.2, relevance=0.1)
        scorer = TemporalDecayScorer(weights=weights)
        item = _make_item(age_seconds=0.0, confidence=1.0)
        scored = scorer.score(item=item, access_count=0, relevance=0.0)

        expected = 0.4 * scored.recency_score + 0.3 * 1.0 + 0.2 * 0.0 + 0.1 * 0.0
        assert math.isclose(scored.score, expected, abs_tol=1e-6)

    def test_relevance_passed_through(self) -> None:
        scorer = TemporalDecayScorer()
        item = _make_item()
        scored = scorer.score(item=item, relevance=0.8)
        assert scored.relevance_score == 0.8

    def test_relevance_clamped(self) -> None:
        scorer = TemporalDecayScorer()
        item = _make_item()
        scored = scorer.score(item=item, relevance=1.5)
        assert scored.relevance_score == 1.0

    def test_score_between_zero_and_one(self) -> None:
        scorer = TemporalDecayScorer()
        item = _make_item(age_seconds=100.0, confidence=0.7)
        scored = scorer.score(item=item, access_count=10, relevance=0.5)
        assert 0.0 <= scored.score <= 1.0


# ---------------------------------------------------------------------------
# Batch scoring
# ---------------------------------------------------------------------------


class TestBatchScoring:
    def test_empty_batch(self) -> None:
        scorer = TemporalDecayScorer()
        result = scorer.score_batch(items=())
        assert result == ()

    def test_sorted_by_score_descending(self) -> None:
        scorer = TemporalDecayScorer()
        fresh = _make_item(key="fresh", age_seconds=0.0, confidence=1.0)
        old = _make_item(key="old", age_seconds=36000.0, confidence=0.3)
        result = scorer.score_batch(items=(old, fresh))
        assert result[0].item.key == "fresh"
        assert result[1].item.key == "old"
        assert result[0].score >= result[1].score

    def test_access_counts_applied(self) -> None:
        scorer = TemporalDecayScorer()
        a = _make_item(key="a", age_seconds=100.0)
        b = _make_item(key="b", age_seconds=100.0)
        counts = {a.full_key: 50, b.full_key: 0}
        result = scorer.score_batch(items=(a, b), access_counts=counts)
        # 'a' has higher frequency, should score higher
        assert result[0].item.key == "a"

    def test_batch_returns_all_items(self) -> None:
        scorer = TemporalDecayScorer()
        items = tuple(_make_item(key=f"item_{i}") for i in range(5))
        result = scorer.score_batch(items=items)
        assert len(result) == 5
