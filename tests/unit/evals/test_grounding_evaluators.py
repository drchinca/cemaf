"""Tests for GroundednessEvaluator and ToolUseSuccessEvaluator.

These evaluators were the two missing deterministic eval dimensions flagged
by the multi-agent review: hallucination detection (groundedness) and
tool-use success rate.
"""

from __future__ import annotations

import pytest

from cemaf.evals.grounding import GroundednessEvaluator, ToolUseSuccessEvaluator
from cemaf.evals.protocols import EvalMetric


@pytest.mark.asyncio
async def test_groundedness_perfect_match_scores_one() -> None:
    evaluator = GroundednessEvaluator(n=3)
    result = await evaluator.evaluate(
        output="solar panels convert sunlight into electricity",
        context={
            "grounding_sources": [
                "solar panels convert sunlight into electricity efficiently",
            ]
        },
    )
    assert result.metric is EvalMetric.GROUNDEDNESS
    assert result.score == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_groundedness_fabricated_output_scores_low() -> None:
    evaluator = GroundednessEvaluator(n=3)
    result = await evaluator.evaluate(
        output="aliens built the pyramids on mars yesterday afternoon",
        context={"grounding_sources": ["solar panels convert sunlight into electricity"]},
    )
    assert result.score < 0.3
    assert not result.passed


@pytest.mark.asyncio
async def test_groundedness_no_sources_fails() -> None:
    evaluator = GroundednessEvaluator()
    result = await evaluator.evaluate(
        output="some claim about something",
        context={},
    )
    assert result.score == 0.0
    assert "No grounding sources" in result.reason


@pytest.mark.asyncio
async def test_groundedness_accepts_context_sources_key() -> None:
    """Alternative key name matches the existing ContextSource convention."""
    evaluator = GroundednessEvaluator(n=2)
    result = await evaluator.evaluate(
        output="cats meow loudly",
        context={"context_sources": ["cats meow loudly at night"]},
    )
    assert result.score == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_groundedness_short_output_passes_vacuously() -> None:
    evaluator = GroundednessEvaluator(n=5)
    result = await evaluator.evaluate(output="hi", context={"grounding_sources": ["x"]})
    assert result.score == 1.0
    assert "too short" in result.reason


@pytest.mark.asyncio
async def test_tool_use_success_all_succeeded_and_referenced() -> None:
    evaluator = ToolUseSuccessEvaluator()
    result = await evaluator.evaluate(
        output="Based on the lookup, the price is seventy two dollars.",
        context={
            "tool_calls": [
                {"name": "lookup_price", "success": True, "result": "the price is seventy two"},
            ]
        },
    )
    assert result.metric is EvalMetric.TOOL_USE_SUCCESS
    assert result.score == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_tool_use_success_partial_failure() -> None:
    evaluator = ToolUseSuccessEvaluator()
    result = await evaluator.evaluate(
        output="Result used.",
        context={
            "tool_calls": [
                {"name": "a", "success": True, "result": "ok"},
                {"name": "b", "success": False, "result": ""},
            ]
        },
    )
    # 50% success, 0% referenced (output doesn't mention tool output)
    # score = 0.7*0.5 + 0.3*0 = 0.35
    assert 0.3 <= result.score <= 0.4


@pytest.mark.asyncio
async def test_tool_use_success_no_tool_calls_passes() -> None:
    evaluator = ToolUseSuccessEvaluator()
    result = await evaluator.evaluate(output="some text", context={"tool_calls": []})
    assert result.score == 1.0


@pytest.mark.asyncio
async def test_tool_use_success_no_context_passes() -> None:
    evaluator = ToolUseSuccessEvaluator()
    result = await evaluator.evaluate(output="text", context=None)
    assert result.score == 1.0
