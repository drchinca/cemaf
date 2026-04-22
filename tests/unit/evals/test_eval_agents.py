"""Tests for QualityGuardAgent."""

import pytest

from cemaf.agents.base import AgentContext
from cemaf.evals.agents import QualityGuardAgent, QualityGuardGoal, QualityGuardResult
from cemaf.evals.police import QualityPolice, QualityPoliceConfig


def _make_context() -> AgentContext:
    """Create a minimal AgentContext for testing."""
    return AgentContext(run_id="test-run", agent_id="QualityGuard")


class TestQualityGuardAgentPassing:
    """Tests for passing evaluations."""

    @pytest.mark.asyncio
    async def test_passing_output(self):
        """Valid JSON output passes default evaluators."""
        police = QualityPolice()
        agent = QualityGuardAgent(quality_police=police)
        goal = QualityGuardGoal(
            output='{"key": "value", "items": [1, 2, 3]}',
            evaluator_names=("length", "json_valid"),
        )

        result = await agent.run(goal=goal, context=_make_context())

        assert result.success
        assert result.output is not None
        assert result.output.passed is True
        assert result.output.overall_score > 0.0

    @pytest.mark.asyncio
    async def test_exact_match_passes(self):
        """Exact match evaluator passes when output equals expected."""
        police = QualityPolice()
        agent = QualityGuardAgent(quality_police=police)
        goal = QualityGuardGoal(
            output="hello world",
            expected="hello world",
            evaluator_names=("exact_match",),
        )

        result = await agent.run(goal=goal, context=_make_context())

        assert result.success
        assert result.output.passed is True
        assert result.output.overall_score == 1.0


class TestQualityGuardAgentFailing:
    """Tests for failing evaluations."""

    @pytest.mark.asyncio
    async def test_failing_output(self):
        """Invalid JSON fails json_valid evaluator."""
        police = QualityPolice()
        agent = QualityGuardAgent(quality_police=police)
        goal = QualityGuardGoal(
            output="not valid json {{{",
            evaluator_names=("json_valid",),
        )

        result = await agent.run(goal=goal, context=_make_context())

        assert result.success  # agent run itself succeeds
        assert result.output.passed is False

    @pytest.mark.asyncio
    async def test_mismatch_fails(self):
        """Exact match fails when output differs from expected."""
        police = QualityPolice()
        agent = QualityGuardAgent(quality_police=police)
        goal = QualityGuardGoal(
            output="hello",
            expected="goodbye",
            evaluator_names=("exact_match",),
        )

        result = await agent.run(goal=goal, context=_make_context())

        assert result.success
        assert result.output.passed is False


class TestQualityGuardPoliceIntegration:
    """Tests for police recording behavior."""

    @pytest.mark.asyncio
    async def test_record_to_police_updates_status(self):
        """Score is recorded when record_to_police is True."""
        police = QualityPolice()
        agent = QualityGuardAgent(quality_police=police)
        goal = QualityGuardGoal(
            output='{"valid": true}',
            evaluator_names=("json_valid",),
            record_to_police=True,
        )

        result = await agent.run(goal=goal, context=_make_context())

        assert result.output.quality_status["scores_count"] == 1

    @pytest.mark.asyncio
    async def test_no_record_to_police_stays_clean(self):
        """Score is NOT recorded when record_to_police is False."""
        police = QualityPolice()
        agent = QualityGuardAgent(quality_police=police)
        goal = QualityGuardGoal(
            output='{"valid": true}',
            evaluator_names=("json_valid",),
            record_to_police=False,
        )

        result = await agent.run(goal=goal, context=_make_context())

        assert result.output.quality_status["scores_count"] == 0

    @pytest.mark.asyncio
    async def test_alert_triggered_on_bad_score(self):
        """Low score triggers quality alert in result."""
        config = QualityPoliceConfig(
            warn_threshold=0.7,
            critical_threshold=0.5,
            halt_threshold=0.3,
        )
        police = QualityPolice(config=config)
        agent = QualityGuardAgent(quality_police=police)
        goal = QualityGuardGoal(
            output="not json {{{",
            evaluator_names=("json_valid",),
            record_to_police=True,
        )

        result = await agent.run(goal=goal, context=_make_context())

        assert result.success
        assert result.output.alert is not None
        assert "level" in result.output.alert


class TestQualityGuardProtocol:
    """Protocol compliance checks."""

    def test_agent_has_required_properties(self):
        """QualityGuardAgent exposes id, description, skills."""
        police = QualityPolice()
        agent = QualityGuardAgent(quality_police=police)

        assert agent.id == "QualityGuard"
        assert len(agent.description) > 0
        assert agent.skills == ()

    def test_result_model_is_frozen(self):
        """QualityGuardResult is immutable."""
        result = QualityGuardResult(
            passed=True,
            overall_score=0.9,
            quality_status={"rolling_mean": 0.9},
        )
        with pytest.raises(Exception):
            result.passed = False
