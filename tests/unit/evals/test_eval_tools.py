"""Tests for eval tools -- RunEvalTool, CheckQualityTool, RecordScoreTool."""

import pytest

from cemaf.evals.police import QualityPolice, QualityPoliceConfig
from cemaf.evals.tools import CheckQualityTool, RecordScoreTool, RunEvalTool
from cemaf.tools.protocols import Tool as ToolProtocol


class TestRunEvalTool:
    """Tests for RunEvalTool."""

    @pytest.mark.asyncio
    async def test_passing_output(self):
        """Long valid JSON string passes length and json_valid evaluators."""
        tool = RunEvalTool()
        result = await tool.execute(
            output='{"key": "value", "number": 42}',
            evaluator_names=["length", "json_valid"],
        )
        assert result.success
        data = result.data
        assert data["overall_passed"] is True
        assert data["overall_score"] > 0.0

    @pytest.mark.asyncio
    async def test_failing_output(self):
        """Invalid JSON fails json_valid evaluator."""
        tool = RunEvalTool()
        result = await tool.execute(
            output="not json {{{",
            evaluator_names=["json_valid"],
        )
        assert result.success  # tool itself succeeds
        data = result.data
        assert data["overall_passed"] is False

    @pytest.mark.asyncio
    async def test_default_evaluators(self):
        """Default evaluator_names used when not specified."""
        tool = RunEvalTool()
        result = await tool.execute(output='{"valid": true}')
        assert result.success
        assert "overall_score" in result.data

    @pytest.mark.asyncio
    async def test_specific_evaluators_exact_match(self):
        """Exact match evaluator passes when output matches expected."""
        tool = RunEvalTool()
        result = await tool.execute(
            output="hello world",
            expected="hello world",
            evaluator_names=["exact_match"],
        )
        assert result.success
        data = result.data
        assert data["overall_passed"] is True
        assert data["overall_score"] == 1.0

    @pytest.mark.asyncio
    async def test_unknown_evaluator_returns_failure(self):
        """Unknown evaluator name returns Result.fail."""
        tool = RunEvalTool()
        result = await tool.execute(
            output="test",
            evaluator_names=["nonexistent_evaluator"],
        )
        assert not result.success
        assert "Unknown evaluator" in result.error


class TestCheckQualityTool:
    """Tests for CheckQualityTool."""

    @pytest.mark.asyncio
    async def test_fresh_police_status(self):
        """Fresh QualityPolice returns clean status."""
        police = QualityPolice()
        tool = CheckQualityTool(quality_police=police)
        result = await tool.execute()

        assert result.success
        data = result.data
        assert data["rolling_mean"] == 1.0
        assert data["halted"] is False
        assert data["alerts_count"] == 0
        assert data["recent_alerts"] == []

    @pytest.mark.asyncio
    async def test_status_after_scores(self):
        """Status reflects recorded scores."""
        police = QualityPolice()
        police.record_score(score=0.8)
        police.record_score(score=0.6)

        tool = CheckQualityTool(quality_police=police)
        result = await tool.execute()

        assert result.success
        data = result.data
        assert data["rolling_mean"] == pytest.approx(0.7)
        assert data["halted"] is False


class TestRecordScoreTool:
    """Tests for RecordScoreTool."""

    @pytest.mark.asyncio
    async def test_good_score_no_alert(self):
        """High score produces no alert."""
        police = QualityPolice()
        tool = RecordScoreTool(quality_police=police)
        result = await tool.execute(score=0.95)

        assert result.success
        data = result.data
        assert data["score_recorded"] == 0.95
        assert "alert" not in data
        assert data["halted"] is False

    @pytest.mark.asyncio
    async def test_bad_score_triggers_alert(self):
        """Score below critical threshold triggers alert."""
        config = QualityPoliceConfig(
            warn_threshold=0.7,
            critical_threshold=0.5,
            halt_threshold=0.3,
        )
        police = QualityPolice(config=config)
        tool = RecordScoreTool(quality_police=police)

        result = await tool.execute(score=0.2)

        assert result.success
        data = result.data
        assert "alert" in data
        assert data["halted"] is True

    @pytest.mark.asyncio
    async def test_record_with_node_id(self):
        """Node ID is passed through to police."""
        police = QualityPolice()
        tool = RecordScoreTool(quality_police=police)
        result = await tool.execute(score=0.9, node_id="node_1")

        assert result.success
        assert result.data["score_recorded"] == 0.9


class TestToolProtocolCompliance:
    """All eval tools satisfy the Tool protocol."""

    def test_run_eval_tool_is_tool(self):
        """RunEvalTool is a Tool protocol implementation."""
        tool = RunEvalTool()
        assert isinstance(tool, ToolProtocol)

    def test_check_quality_tool_is_tool(self):
        """CheckQualityTool is a Tool protocol implementation."""
        police = QualityPolice()
        tool = CheckQualityTool(quality_police=police)
        assert isinstance(tool, ToolProtocol)

    def test_record_score_tool_is_tool(self):
        """RecordScoreTool is a Tool protocol implementation."""
        police = QualityPolice()
        tool = RecordScoreTool(quality_police=police)
        assert isinstance(tool, ToolProtocol)
