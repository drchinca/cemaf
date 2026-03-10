"""Shared fixtures and fakes for eval tests."""

from typing import Any

from cemaf.core.types import JSON
from cemaf.evals.protocols import EvalMetric, EvalResult


class FakeEvaluator:
    """Configurable fake evaluator for testing."""

    def __init__(
        self,
        *,
        score: float = 1.0,
        passed: bool | None = None,
        metric: EvalMetric = EvalMetric.CUSTOM,
        name: str = "FakeEvaluator",
        reason: str | None = None,
        confidence: float = 1.0,
    ) -> None:
        self._score = score
        self._passed = passed if passed is not None else score >= 0.5
        self._metric = metric
        self._name = name
        self._reason = reason if reason is not None else f"Fake: score={score}"
        self._confidence = confidence

    @property
    def metric(self) -> EvalMetric:
        return self._metric

    @property
    def name(self) -> str:
        return self._name

    async def evaluate(
        self,
        output: Any,
        expected: Any | None = None,
        context: JSON | None = None,
    ) -> EvalResult:
        """Return preconfigured result."""
        return EvalResult(
            metric=self._metric,
            score=self._score,
            passed=self._passed,
            reason=self._reason,
            confidence=self._confidence,
        )


class FailingEvaluator:
    """Evaluator that raises an exception for error path testing."""

    def __init__(self, *, error_message: str = "Eval failed") -> None:
        self._error_message = error_message

    @property
    def metric(self) -> EvalMetric:
        return EvalMetric.CUSTOM

    @property
    def name(self) -> str:
        return "FailingEvaluator"

    async def evaluate(
        self,
        output: Any,
        expected: Any | None = None,
        context: JSON | None = None,
    ) -> EvalResult:
        """Raise an exception to test error paths."""
        raise RuntimeError(self._error_message)
