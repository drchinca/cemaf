"""Deterministic evaluators for groundedness and tool-use success.

These are the two missing eval dimensions flagged by the multi-agent review:
- Groundedness: fraction of output n-grams supported by the provided context.
  Answers "did the LLM make stuff up beyond what the retrieved context said?"
- ToolUseSuccess: did the tool call succeed AND did the LLM's subsequent
  turn reference the result?

Both are heuristic — a proper production setup pairs these with an LLM-judge
for high-stakes workloads, but the deterministic signal runs at zero cost
and catches the most common failure modes.
"""

from __future__ import annotations

import re
from typing import Any

from cemaf.core.types import JSON
from cemaf.evals.protocols import (
    BaseEvaluator,
    EvalConfig,
    EvalMetric,
    EvalResult,
)

_WORD_RE = re.compile(r"[a-z0-9]+")


def _ngrams(*, text: str, n: int) -> set[tuple[str, ...]]:
    """Return the set of n-grams (lowercased, alphanumeric tokens) for `text`."""
    tokens = _WORD_RE.findall(text.lower())
    if len(tokens) < n:
        return set()
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


class GroundednessEvaluator(BaseEvaluator):
    """Fraction of output n-grams that appear in the provided context.

    context parameter is expected to carry a `grounding_sources: list[str]`
    or `context_sources: list[str]` key — a list of source documents the
    output should be grounded in. If absent, the evaluator falls back to
    concatenating all string values in the context dict.

    Scoring: score = (output_ngrams ∩ source_ngrams) / |output_ngrams|
    A score of 1.0 means every n-gram in the output appears verbatim in
    some source. Low scores flag hallucination.
    """

    def __init__(
        self,
        n: int = 3,
        config: EvalConfig | None = None,
    ) -> None:
        super().__init__(config)
        self._n = max(1, n)

    @property
    def metric(self) -> EvalMetric:
        return EvalMetric.GROUNDEDNESS

    async def evaluate(
        self,
        output: Any,
        expected: Any | None = None,
        context: JSON | None = None,
    ) -> EvalResult:
        out_text = str(output) if output is not None else ""
        out_ngrams = _ngrams(text=out_text, n=self._n)
        if not out_ngrams:
            return self._make_result(
                score=1.0,
                reason=f"Output too short for {self._n}-gram grounding; passing vacuously",
                actual=output,
            )

        source_text = _collect_sources(context=context)
        source_ngrams = _ngrams(text=source_text, n=self._n)

        if not source_ngrams:
            return self._make_result(
                score=0.0,
                reason="No grounding sources provided in context",
                actual=output,
                confidence=0.5,
            )

        overlap = out_ngrams & source_ngrams
        score = len(overlap) / len(out_ngrams)
        return self._make_result(
            score=score,
            reason=(f"{len(overlap)}/{len(out_ngrams)} output {self._n}-grams grounded in sources"),
            actual=output,
        )


def _collect_sources(*, context: JSON | None) -> str:
    """Extract source text from context — explicit keys or fallback aggregation."""
    if context is None:
        return ""
    explicit = context.get("grounding_sources") or context.get("context_sources")
    if isinstance(explicit, list):
        return "\n".join(str(item) for item in explicit)
    if isinstance(explicit, str):
        return explicit
    # Fallback: concatenate all string-like values
    parts: list[str] = []
    for key, value in context.items():
        if key.startswith("_"):
            continue
        if isinstance(value, str):
            parts.append(value)
    return "\n".join(parts)


class ToolUseSuccessEvaluator(BaseEvaluator):
    """Evaluates whether tool calls succeeded and were utilized.

    Expects `context["tool_calls"]` to be a list of dicts with:
      - `success: bool` — did the tool call complete without error?
      - `result: str` — the tool result content (optional)
      - `name: str` — the tool name

    Score = (successful_calls / total_calls) weighted by whether the output
    text references any tool result content. If no tool calls were made,
    passes vacuously with score 1.0.
    """

    @property
    def metric(self) -> EvalMetric:
        return EvalMetric.TOOL_USE_SUCCESS

    async def evaluate(
        self,
        output: Any,
        expected: Any | None = None,
        context: JSON | None = None,
    ) -> EvalResult:
        tool_calls = (context or {}).get("tool_calls")
        if not tool_calls or not isinstance(tool_calls, list):
            return self._make_result(
                score=1.0,
                reason="No tool calls were made; passing vacuously",
                actual=output,
            )

        total = len(tool_calls)
        successful = sum(1 for call in tool_calls if isinstance(call, dict) and call.get("success") is True)
        if total == 0:
            return self._make_result(score=1.0, reason="Empty tool_calls list")

        success_rate = successful / total
        # Bonus: did the output actually reference tool results?
        out_text = str(output or "").lower()
        referenced = 0
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            result_text = str(call.get("result", "")).lower()
            # Count as referenced if any 4-word slice of the tool result
            # appears in the output. Cheap heuristic, robust enough.
            result_tokens = _WORD_RE.findall(result_text)
            if len(result_tokens) < 4:
                if result_text and result_text in out_text:
                    referenced += 1
                continue
            for i in range(len(result_tokens) - 3):
                probe = " ".join(result_tokens[i : i + 4])
                if probe in out_text:
                    referenced += 1
                    break

        reference_rate = referenced / total if total else 0.0
        # Blend: success is necessary, reference is a bonus.
        score = 0.7 * success_rate + 0.3 * reference_rate
        return self._make_result(
            score=score,
            reason=(
                f"{successful}/{total} tool calls succeeded; "
                f"{referenced}/{total} results referenced in output"
            ),
            actual=output,
        )


__all__ = ["GroundednessEvaluator", "ToolUseSuccessEvaluator"]
