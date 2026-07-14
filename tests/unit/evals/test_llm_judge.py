"""Tests for LLM-as-Judge evaluator."""

import pytest

from cemaf.evals.llm_judge import (
    DEFAULT_JUDGE_PROMPTS,
    JudgeCriteria,
    JudgePrompt,
    LLMJudgeEvaluator,
)
from cemaf.evals.protocols import EvalMetric
from cemaf.llm.mock import MockLLMClient


class TestScoreExtraction:
    """Tests for score extraction from LLM response text."""

    @pytest.mark.asyncio
    async def test_extracts_integer_score(self) -> None:
        """Extracts integer score from 'Score: N' format."""
        mock = MockLLMClient(responses=["Score: 8\nReason: Good answer"])
        evaluator = LLMJudgeEvaluator(llm_client=mock, criteria=JudgeCriteria.HELPFULNESS)
        result = await evaluator.evaluate(output="test output")

        # Score 8/10 normalized to 0.8
        assert result.score == pytest.approx(0.8, abs=0.01)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_extracts_decimal_score(self) -> None:
        """Extracts decimal score from response."""
        mock = MockLLMClient(responses=["Score: 7.5\nReason: Decent"])
        evaluator = LLMJudgeEvaluator(llm_client=mock, criteria=JudgeCriteria.HELPFULNESS)
        result = await evaluator.evaluate(output="test output")

        assert result.score == pytest.approx(0.75, abs=0.01)

    @pytest.mark.asyncio
    async def test_score_normalization_above_one(self) -> None:
        """Scores > 1.0 are normalized by dividing by 10."""
        mock = MockLLMClient(responses=["Score: 10\nReason: Perfect"])
        evaluator = LLMJudgeEvaluator(llm_client=mock, criteria=JudgeCriteria.HELPFULNESS)
        result = await evaluator.evaluate(output="test output")

        assert result.score == pytest.approx(1.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_score_at_or_below_one_not_normalized(self) -> None:
        """Scores <= 1.0 are kept as-is."""
        mock = MockLLMClient(responses=["Score: 0.9\nReason: Almost perfect"])
        evaluator = LLMJudgeEvaluator(llm_client=mock, criteria=JudgeCriteria.HELPFULNESS)
        result = await evaluator.evaluate(output="test output")

        assert result.score == pytest.approx(0.9, abs=0.01)

    @pytest.mark.asyncio
    async def test_non_numeric_defaults_to_half(self) -> None:
        """When LLM returns no parseable score, defaults to 0.5."""
        mock = MockLLMClient(responses=["This response has no score pattern"])
        evaluator = LLMJudgeEvaluator(llm_client=mock, criteria=JudgeCriteria.HELPFULNESS)
        result = await evaluator.evaluate(output="test output")

        assert result.score == pytest.approx(0.5, abs=0.01)

    @pytest.mark.asyncio
    async def test_zero_score(self) -> None:
        """Zero score is extracted and normalized correctly."""
        mock = MockLLMClient(responses=["Score: 0\nReason: Terrible"])
        evaluator = LLMJudgeEvaluator(llm_client=mock, criteria=JudgeCriteria.HELPFULNESS)
        result = await evaluator.evaluate(output="test output")

        assert result.score == pytest.approx(0.0, abs=0.01)
        assert result.passed is False


class TestReasonExtraction:
    """Tests for reason extraction from LLM response."""

    @pytest.mark.asyncio
    async def test_extracts_reason(self) -> None:
        """Extracts text after 'Reason:' label."""
        mock = MockLLMClient(responses=["Score: 7\nReason: The response was helpful and clear"])
        evaluator = LLMJudgeEvaluator(llm_client=mock, criteria=JudgeCriteria.HELPFULNESS)
        result = await evaluator.evaluate(output="test")

        assert "helpful" in result.reason
        assert "clear" in result.reason

    @pytest.mark.asyncio
    async def test_truncates_long_reason(self) -> None:
        """Reasons longer than 500 chars are truncated."""
        long_reason = "x" * 600
        mock = MockLLMClient(responses=[f"Score: 5\nReason: {long_reason}"])
        evaluator = LLMJudgeEvaluator(llm_client=mock, criteria=JudgeCriteria.HELPFULNESS)
        result = await evaluator.evaluate(output="test")

        assert len(result.reason) <= 500


class TestLLMJudgeEvaluator:
    """Tests for LLMJudgeEvaluator initialization and behavior."""

    def test_criteria_to_metric_mapping(self) -> None:
        """Each criteria maps to the correct EvalMetric."""
        mock = MockLLMClient()

        for criteria, expected_metric in [
            (JudgeCriteria.HELPFULNESS, EvalMetric.HELPFULNESS),
            (JudgeCriteria.COHERENCE, EvalMetric.COHERENCE),
            (JudgeCriteria.RELEVANCE, EvalMetric.RELEVANCE),
            (JudgeCriteria.FACTUALITY, EvalMetric.FACTUALITY),
        ]:
            evaluator = LLMJudgeEvaluator(llm_client=mock, criteria=criteria)
            assert evaluator.metric == expected_metric

    def test_custom_criteria_maps_to_custom_metric(self) -> None:
        """CUSTOM criteria requires a custom_prompt and maps to CUSTOM metric."""
        mock = MockLLMClient()
        custom_prompt = JudgePrompt(
            criteria=JudgeCriteria.CUSTOM,
            system_prompt="Rate it",
            user_template="{output}",
        )
        evaluator = LLMJudgeEvaluator(
            llm_client=mock,
            criteria=JudgeCriteria.CUSTOM,
            custom_prompt=custom_prompt,
        )
        assert evaluator.metric == EvalMetric.CUSTOM

    def test_missing_prompt_raises(self) -> None:
        """Criteria without a default prompt and no custom_prompt raises ValueError."""
        mock = MockLLMClient()
        with pytest.raises(ValueError, match="No prompt defined"):
            LLMJudgeEvaluator(
                llm_client=mock,
                criteria=JudgeCriteria.COMPLETENESS,
            )

    def test_name_includes_criteria(self) -> None:
        """Evaluator name includes the criteria value."""
        mock = MockLLMClient()
        evaluator = LLMJudgeEvaluator(llm_client=mock, criteria=JudgeCriteria.HELPFULNESS)
        assert "helpfulness" in evaluator.name.lower()

    @pytest.mark.asyncio
    async def test_llm_failure_returns_zero_score(self) -> None:
        """When LLM call fails, score is 0.0 with error reason."""

        class _FailingLLMClient(MockLLMClient):
            async def complete(self, messages, tools=None, config_override=None, **kwargs):
                from cemaf.llm.protocols import CompletionResult

                return CompletionResult.fail(
                    error="Connection timeout",
                )

        evaluator = LLMJudgeEvaluator(
            llm_client=_FailingLLMClient(),
            criteria=JudgeCriteria.HELPFULNESS,
        )
        result = await evaluator.evaluate(output="test")

        assert result.score == 0.0
        assert result.confidence == 0.0
        assert "failed" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_confidence_is_set(self) -> None:
        """Successful evaluations have confidence of 0.8."""
        mock = MockLLMClient(responses=["Score: 7\nReason: Good"])
        evaluator = LLMJudgeEvaluator(llm_client=mock, criteria=JudgeCriteria.HELPFULNESS)
        result = await evaluator.evaluate(output="test")

        assert result.confidence == pytest.approx(0.8, abs=0.01)

    @pytest.mark.asyncio
    async def test_passes_context_and_expected(self) -> None:
        """Context and expected values are actually embedded in the LLM prompt.

        Regression: previously this test only asserted 'answer' (the output)
        appeared — which it does trivially. The expected and context values
        were not actually verified. A regression that dropped expected=/
        context= from the prompt template would have passed.
        """
        mock = MockLLMClient(responses=["Score: 5\nReason: ok"])
        evaluator = LLMJudgeEvaluator(llm_client=mock, criteria=JudgeCriteria.HELPFULNESS)
        await evaluator.evaluate(
            output="my-output-text",
            expected="my-expected-value",
            context={"query": "my-context-query"},
        )

        assert mock.call_count == 1
        last_call = mock.calls[0]
        full_prompt = "\n".join(str(m.content) for m in last_call)
        assert "my-output-text" in full_prompt, "output must appear in prompt"
        assert "my-expected-value" in full_prompt, "expected value must appear in prompt"
        assert "my-context-query" in full_prompt, "context must appear in prompt"


class TestDefaultJudgePrompts:
    """Tests for DEFAULT_JUDGE_PROMPTS dictionary."""

    def test_helpfulness_prompt_exists(self) -> None:
        assert JudgeCriteria.HELPFULNESS in DEFAULT_JUDGE_PROMPTS

    def test_coherence_prompt_exists(self) -> None:
        assert JudgeCriteria.COHERENCE in DEFAULT_JUDGE_PROMPTS

    def test_relevance_prompt_exists(self) -> None:
        assert JudgeCriteria.RELEVANCE in DEFAULT_JUDGE_PROMPTS

    def test_factuality_prompt_exists(self) -> None:
        assert JudgeCriteria.FACTUALITY in DEFAULT_JUDGE_PROMPTS

    def test_prompts_have_score_extraction_pattern(self) -> None:
        """All default prompts have a score extraction regex pattern."""
        for criteria, prompt in DEFAULT_JUDGE_PROMPTS.items():
            assert prompt.score_extraction_pattern, f"Missing pattern for {criteria}"

    def test_prompts_have_system_and_user_templates(self) -> None:
        """All default prompts have system_prompt and user_template."""
        for criteria, prompt in DEFAULT_JUDGE_PROMPTS.items():
            assert prompt.system_prompt, f"Missing system_prompt for {criteria}"
            assert prompt.user_template, f"Missing user_template for {criteria}"
