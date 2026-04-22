"""Tests for hierarchical multi-tier evaluator."""

import pytest

from cemaf.evals.evaluators import ContainsEvaluator, LengthEvaluator
from cemaf.evals.hierarchy import HierarchicalJudge, HierarchicalJudgeConfig
from cemaf.evals.protocols import EvalMetric, Evaluator
from tests.unit.evals.conftest import FakeEvaluator


class TestProtocol:
    """Protocol compliance tests."""

    def test_implements_evaluator_protocol(self) -> None:
        """HierarchicalJudge satisfies the Evaluator protocol."""
        judge = HierarchicalJudge(
            tier1_evaluators=(ContainsEvaluator(),),
        )
        assert isinstance(judge, Evaluator)
        assert judge.name == "HierarchicalJudge"
        assert judge.metric == EvalMetric.CUSTOM


class TestTier1Only:
    """Tests when only tier-1 evaluators are configured."""

    @pytest.mark.asyncio
    async def test_tier1_only_when_no_tier2(self) -> None:
        """Returns tier-1 result when no tier-2 is configured."""
        judge = HierarchicalJudge(
            tier1_evaluators=(
                ContainsEvaluator(),
                LengthEvaluator(min_length=3),
            ),
        )
        result = await judge.evaluate(
            output="hello world",
            expected="hello",
        )

        assert result.passed is True
        assert result.score > 0.0
        assert "no tier 2 configured" in result.reason.lower()
        assert result.metadata["tiers_run"] == [1]

    @pytest.mark.asyncio
    async def test_tier1_failure_stops_escalation(self) -> None:
        """Tier-1 failure prevents tier-2 and tier-3 from running."""
        fake_tier2 = FakeEvaluator(score=1.0)
        judge = HierarchicalJudge(
            tier1_evaluators=(ContainsEvaluator(),),
            tier2_evaluator=fake_tier2,
            tier3_evaluator=FakeEvaluator(score=1.0),
        )
        # "hello" does not contain "xyz"
        result = await judge.evaluate(
            output="hello",
            expected="xyz",
        )

        assert result.passed is False
        assert result.metadata["tiers_run"] == [1]
        assert len(result.metadata["tier_scores"]) == 1


class TestTier2:
    """Tests for tier-2 escalation."""

    @pytest.mark.asyncio
    async def test_tier2_clear_pass_skips_tier3(self) -> None:
        """High tier-2 score (outside ambiguity range) skips tier-3."""
        judge = HierarchicalJudge(
            tier1_evaluators=(ContainsEvaluator(),),
            tier2_evaluator=FakeEvaluator(score=0.9, passed=True, reason="semantic match"),
            tier3_evaluator=FakeEvaluator(score=0.5),
            config=HierarchicalJudgeConfig(
                tier3_ambiguity_range=(0.4, 0.7),
                tier3_sample_rate=0.0,
            ),
        )
        result = await judge.evaluate(
            output="hello world",
            expected="hello",
        )

        assert result.passed is True
        assert result.score == pytest.approx(0.9)
        assert result.metadata["tiers_run"] == [1, 2]

    @pytest.mark.asyncio
    async def test_tier2_ambiguous_triggers_tier3(self) -> None:
        """Tier-2 score in ambiguity range triggers tier-3."""
        judge = HierarchicalJudge(
            tier1_evaluators=(ContainsEvaluator(),),
            tier2_evaluator=FakeEvaluator(score=0.55, passed=True, reason="borderline"),
            tier3_evaluator=FakeEvaluator(score=0.85, passed=True, reason="llm says good"),
            config=HierarchicalJudgeConfig(
                tier3_ambiguity_range=(0.4, 0.7),
                tier3_sample_rate=0.0,
            ),
        )
        result = await judge.evaluate(
            output="hello world",
            expected="hello",
        )

        assert result.passed is True
        assert result.score == pytest.approx(0.85)
        assert result.metadata["tiers_run"] == [1, 2, 3]
        assert "llm says good" in result.reason


class TestTier3Sampling:
    """Tests for tier-3 sampling behavior."""

    @pytest.mark.asyncio
    async def test_tier3_sample_rate(self) -> None:
        """Tier-3 runs on sample even when tier-2 is not ambiguous."""
        judge = HierarchicalJudge(
            tier1_evaluators=(ContainsEvaluator(),),
            tier2_evaluator=FakeEvaluator(score=0.9, passed=True),
            tier3_evaluator=FakeEvaluator(score=0.95, passed=True, reason="sampled judge"),
            config=HierarchicalJudgeConfig(
                tier3_ambiguity_range=(0.4, 0.7),
                tier3_sample_rate=1.0,  # always sample
            ),
        )
        result = await judge.evaluate(
            output="hello world",
            expected="hello",
        )

        assert result.metadata["tiers_run"] == [1, 2, 3]
        assert result.score == pytest.approx(0.95)


class TestMetadata:
    """Tests for metadata tracking."""

    @pytest.mark.asyncio
    async def test_tiers_run_metadata_tracks_tiers(self) -> None:
        """Metadata correctly records which tiers ran and their scores."""
        judge = HierarchicalJudge(
            tier1_evaluators=(ContainsEvaluator(),),
            tier2_evaluator=FakeEvaluator(score=0.5, passed=True),
            tier3_evaluator=FakeEvaluator(score=0.75, passed=True),
            config=HierarchicalJudgeConfig(
                tier3_ambiguity_range=(0.4, 0.7),
            ),
        )
        result = await judge.evaluate(
            output="hello world",
            expected="hello",
        )

        tiers_run = result.metadata["tiers_run"]
        tier_scores = result.metadata["tier_scores"]

        assert tiers_run == [1, 2, 3]
        assert len(tier_scores) == 3
        assert all(isinstance(s, float) for s in tier_scores)

    @pytest.mark.asyncio
    async def test_all_tiers_pass(self) -> None:
        """All three tiers execute and pass with correct final score."""
        judge = HierarchicalJudge(
            tier1_evaluators=(
                ContainsEvaluator(),
                LengthEvaluator(min_length=5),
            ),
            tier2_evaluator=FakeEvaluator(score=0.6, passed=True),
            tier3_evaluator=FakeEvaluator(
                score=0.92,
                passed=True,
                reason="excellent response",
                confidence=0.8,
            ),
            config=HierarchicalJudgeConfig(
                tier3_ambiguity_range=(0.4, 0.7),
            ),
        )
        result = await judge.evaluate(
            output="hello world this is a long enough output",
            expected="hello",
        )

        assert result.passed is True
        assert result.score == pytest.approx(0.92)
        assert result.confidence == pytest.approx(0.8)
        assert result.metadata["tiers_run"] == [1, 2, 3]
        assert "excellent response" in result.reason
