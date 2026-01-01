"""
LLM-as-Judge evaluator - Uses an LLM to evaluate outputs.

Useful for subjective qualities like:
- Helpfulness
- Coherence
- Relevance
- Factuality
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from cemaf.core.types import JSON
from cemaf.evals.protocols import (
    BaseEvaluator,
    EvalConfig,
    EvalMetric,
    EvalResult,
)
from cemaf.llm.protocols import LLMClient, Message


class JudgeCriteria(str, Enum):
    """Standard judging criteria."""

    HELPFULNESS = "helpfulness"
    COHERENCE = "coherence"
    RELEVANCE = "relevance"
    FACTUALITY = "factuality"
    COMPLETENESS = "completeness"
    CONCISENESS = "conciseness"
    SAFETY = "safety"
    CUSTOM = "custom"


@dataclass(frozen=True)
class JudgePrompt:
    """
    Prompt template for LLM judge.
    """

    criteria: JudgeCriteria
    system_prompt: str
    user_template: str  # {output}, {expected}, {context} placeholders
    score_extraction_pattern: str = r"Score:\s*(\d+(?:\.\d+)?)"


# Default prompts for each criteria
DEFAULT_JUDGE_PROMPTS: dict[JudgeCriteria, JudgePrompt] = {
    JudgeCriteria.HELPFULNESS: JudgePrompt(
        criteria=JudgeCriteria.HELPFULNESS,
        system_prompt="""You are an expert evaluator. Rate the helpfulness of the response on a scale of 0-10.
Consider:
- Does it address the user's need?
- Is it actionable and practical?
- Is it clear and understandable?

Respond with:
Score: <number>
Reason: <brief explanation>""",
        user_template="""Evaluate this response:

{output}

Context: {context}
Expected: {expected}""",
    ),
    JudgeCriteria.COHERENCE: JudgePrompt(
        criteria=JudgeCriteria.COHERENCE,
        system_prompt="""You are an expert evaluator. Rate the coherence of the response on a scale of 0-10.
Consider:
- Is it logically structured?
- Does it flow naturally?
- Are there contradictions?

Respond with:
Score: <number>
Reason: <brief explanation>""",
        user_template="""Evaluate this response for coherence:

{output}""",
    ),
    JudgeCriteria.RELEVANCE: JudgePrompt(
        criteria=JudgeCriteria.RELEVANCE,
        system_prompt="""You are an expert evaluator. Rate the relevance of the response on a scale of 0-10.
Consider:
- Does it address the actual question/task?
- Is it on-topic?
- Does it include unnecessary information?

Respond with:
Score: <number>
Reason: <brief explanation>""",
        user_template="""Question/Task: {context}

Response to evaluate:
{output}

Expected answer (if any): {expected}""",
    ),
    JudgeCriteria.FACTUALITY: JudgePrompt(
        criteria=JudgeCriteria.FACTUALITY,
        system_prompt="""You are an expert evaluator. Rate the factual accuracy on a scale of 0-10.
Consider:
- Are claims verifiable?
- Are there obvious errors?
- Is information up-to-date?

Respond with:
Score: <number>
Reason: <brief explanation>""",
        user_template="""Evaluate factual accuracy:

{output}

Reference (if any): {expected}""",
    ),
}


class LLMJudgeEvaluator(BaseEvaluator):
    """
    LLM-as-Judge evaluator.

    Uses an LLM to evaluate subjective qualities of outputs.

    Usage:
        evaluator = LLMJudgeEvaluator(
            llm_client=my_client,
            criteria=JudgeCriteria.HELPFULNESS,
        )
        result = await evaluator.evaluate(output="Hello!", context={"query": "greet me"})
    """

    def __init__(
        self,
        llm_client: LLMClient,
        criteria: JudgeCriteria = JudgeCriteria.HELPFULNESS,
        custom_prompt: JudgePrompt | None = None,
        config: EvalConfig | None = None,
    ) -> None:
        super().__init__(config, name=f"LLMJudge_{criteria.value}")
        self._llm = llm_client
        self._criteria = criteria
        self._prompt = custom_prompt or DEFAULT_JUDGE_PROMPTS.get(criteria)

        if not self._prompt:
            raise ValueError(f"No prompt defined for criteria: {criteria}")

    @property
    def metric(self) -> EvalMetric:
        # Map criteria to metrics
        mapping = {
            JudgeCriteria.HELPFULNESS: EvalMetric.HELPFULNESS,
            JudgeCriteria.COHERENCE: EvalMetric.COHERENCE,
            JudgeCriteria.RELEVANCE: EvalMetric.RELEVANCE,
            JudgeCriteria.FACTUALITY: EvalMetric.FACTUALITY,
        }
        return mapping.get(self._criteria, EvalMetric.CUSTOM)

    async def evaluate(
        self,
        output: Any,
        expected: Any | None = None,
        context: JSON | None = None,
    ) -> EvalResult:
        """Evaluate using LLM as judge."""
        import re

        # Build prompt
        user_content = self._prompt.user_template.format(
            output=str(output),
            expected=str(expected) if expected else "N/A",
            context=str(context) if context else "N/A",
        )

        messages = [
            Message.system(self._prompt.system_prompt),
            Message.user(user_content),
        ]

        # Call LLM
        result = await self._llm.complete(messages)

        if not result.success or not result.message:
            return self._make_result(
                score=0.0,
                reason=f"LLM call failed: {result.error}",
                confidence=0.0,
            )

        response = result.message.content

        # Extract score
        score_match = re.search(self._prompt.score_extraction_pattern, response)
        if score_match:
            raw_score = float(score_match.group(1))
            # Normalize to 0-1 if on 0-10 scale
            score = raw_score / 10.0 if raw_score > 1.0 else raw_score
        else:
            score = 0.5  # Default if extraction fails

        # Extract reason
        reason_match = re.search(r"Reason:\s*(.+)", response, re.DOTALL)
        reason = reason_match.group(1).strip() if reason_match else response

        return self._make_result(
            score=score,
            reason=reason[:500],  # Truncate long reasons
            expected=expected,
            actual=output,
            confidence=0.8,  # LLM judgments have inherent uncertainty
        )
