"""
Composite evaluators - Combine multiple evaluators.

Provides:
- CompositeEvaluator: Run multiple evaluators, aggregate results
- EvalSuite: Named collection of evaluators for test suites
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from cemaf.core.types import JSON
from cemaf.core.utils import utc_now
from cemaf.evals.protocols import (
    EvalConfig,
    EvalMetric,
    EvalResult,
    Evaluator,
)


@dataclass(frozen=True)
class CompositeEvalResult:
    """
    Result of running multiple evaluators.
    """

    results: tuple[EvalResult, ...]
    overall_score: float
    overall_passed: bool
    failed_metrics: tuple[EvalMetric, ...]
    evaluated_at: datetime = field(default_factory=utc_now)
    metadata: JSON = field(default_factory=dict)

    @property
    def all_passed(self) -> bool:
        """Whether all evaluators passed."""
        return all(r.passed for r in self.results)

    @property
    def pass_rate(self) -> float:
        """Percentage of evaluators that passed."""
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.passed) / len(self.results)

    def get_result(self, metric: EvalMetric) -> EvalResult | None:
        """Get result for a specific metric."""
        for r in self.results:
            if r.metric == metric:
                return r
        return None

    def to_dict(self) -> JSON:
        """Serialize to dict."""
        return {
            "overall_score": self.overall_score,
            "overall_passed": self.overall_passed,
            "pass_rate": self.pass_rate,
            "failed_metrics": [m.value for m in self.failed_metrics],
            "results": [
                {
                    "metric": r.metric.value,
                    "score": r.score,
                    "passed": r.passed,
                    "reason": r.reason,
                }
                for r in self.results
            ],
        }


class AggregationStrategy:
    """Strategies for aggregating multiple scores."""

    @staticmethod
    def mean(scores: list[float]) -> float:
        """Average of all scores."""
        return sum(scores) / len(scores) if scores else 0.0

    @staticmethod
    def min(scores: list[float]) -> float:
        """Minimum score (most strict)."""
        return min(scores) if scores else 0.0

    @staticmethod
    def max(scores: list[float]) -> float:
        """Maximum score (most lenient)."""
        return max(scores) if scores else 0.0

    @staticmethod
    def weighted(scores: list[float], weights: list[float]) -> float:
        """Weighted average."""
        if not scores or not weights:
            return 0.0
        total_weight = sum(weights)
        if total_weight == 0:
            return 0.0
        return sum(s * w for s, w in zip(scores, weights, strict=False)) / total_weight


class CompositeEvaluator:
    """
    Combines multiple evaluators into one.

    Runs all evaluators and aggregates results.

    Usage:
        composite = CompositeEvaluator([
            ExactMatchEvaluator(),
            LengthEvaluator(min_length=10),
            JSONSchemaEvaluator(schema=my_schema),
        ])
        result = await composite.evaluate(output, expected)
    """

    def __init__(
        self,
        evaluators: list[Evaluator],
        aggregation: str = "mean",  # "mean", "min", "max"
        weights: list[float] | None = None,
        require_all_pass: bool = False,
        config: EvalConfig | None = None,
    ) -> None:
        self._evaluators = evaluators
        self._aggregation = aggregation
        self._weights = weights or [1.0] * len(evaluators)
        self._require_all = require_all_pass
        self._config = config or EvalConfig()

    async def evaluate(
        self,
        output: Any,
        expected: Any | None = None,
        context: JSON | None = None,
    ) -> CompositeEvalResult:
        """Run all evaluators and aggregate."""
        results: list[EvalResult] = []

        for evaluator in self._evaluators:
            result = await evaluator.evaluate(output, expected, context)
            results.append(result)

            # Fail fast if configured
            if self._config.fail_fast and not result.passed:
                break

        # Aggregate scores
        scores = [r.score for r in results]

        if self._aggregation == "min":
            overall_score = AggregationStrategy.min(scores)
        elif self._aggregation == "max":
            overall_score = AggregationStrategy.max(scores)
        elif self._aggregation == "weighted":
            overall_score = AggregationStrategy.weighted(scores, self._weights)
        else:
            overall_score = AggregationStrategy.mean(scores)

        # Determine overall pass
        if self._require_all:
            overall_passed = all(r.passed for r in results)
        else:
            overall_passed = overall_score >= self._config.pass_threshold

        failed_metrics = tuple(r.metric for r in results if not r.passed)

        return CompositeEvalResult(
            results=tuple(results),
            overall_score=overall_score,
            overall_passed=overall_passed,
            failed_metrics=failed_metrics,
        )


@dataclass
class EvalCase:
    """A single evaluation test case."""

    name: str
    output: Any
    expected: Any | None = None
    context: JSON | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class EvalSuiteResult:
    """Result of running an evaluation suite."""

    suite_name: str
    case_results: tuple[tuple[str, CompositeEvalResult], ...]  # (case_name, result)
    overall_pass_rate: float
    total_cases: int
    passed_cases: int
    failed_cases: int
    duration_ms: float = 0.0

    def to_dict(self) -> JSON:
        """Serialize to dict."""
        return {
            "suite_name": self.suite_name,
            "overall_pass_rate": self.overall_pass_rate,
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "failed_cases": self.failed_cases,
            "duration_ms": self.duration_ms,
            "cases": {name: result.to_dict() for name, result in self.case_results},
        }


class EvalSuite:
    """
    Named collection of evaluators and test cases.

    Useful for regression testing and benchmarking.

    Usage:
        suite = EvalSuite(
            name="quality_checks",
            evaluators=[ExactMatchEvaluator(), LengthEvaluator()],
        )
        suite.add_case(EvalCase(
            name="greeting",
            output="Hello!",
            expected="Hello!",
        ))
        results = await suite.run()
    """

    def __init__(
        self,
        name: str,
        evaluators: list[Evaluator],
        config: EvalConfig | None = None,
    ) -> None:
        self._name = name
        self._composite = CompositeEvaluator(evaluators, config=config)
        self._cases: list[EvalCase] = []

    @property
    def name(self) -> str:
        return self._name

    def add_case(self, case: EvalCase) -> None:
        """Add a test case."""
        self._cases.append(case)

    def add_cases(self, cases: list[EvalCase]) -> None:
        """Add multiple test cases."""
        self._cases.extend(cases)

    async def run(self, filter_tags: list[str] | None = None) -> EvalSuiteResult:
        """
        Run all test cases.

        Args:
            filter_tags: Only run cases with these tags

        Returns:
            EvalSuiteResult with all results
        """
        start_time = utc_now()

        # Filter cases by tags
        cases = self._cases
        if filter_tags:
            cases = [c for c in cases if any(t in c.tags for t in filter_tags)]

        # Run each case
        case_results: list[tuple[str, CompositeEvalResult]] = []
        passed = 0

        for case in cases:
            result = await self._composite.evaluate(
                case.output,
                case.expected,
                case.context,
            )
            case_results.append((case.name, result))

            if result.overall_passed:
                passed += 1

        end_time = utc_now()
        duration = (end_time - start_time).total_seconds() * 1000

        return EvalSuiteResult(
            suite_name=self._name,
            case_results=tuple(case_results),
            overall_pass_rate=passed / len(cases) if cases else 0.0,
            total_cases=len(cases),
            passed_cases=passed,
            failed_cases=len(cases) - passed,
            duration_ms=duration,
        )
