"""Evaluation protocols — taxonomy of metrics, results, evaluators.

The contracts every evaluator implements. Three axes to understand:

**EvalMetric (enum)** — what is being measured:
- Binary: `PASS_FAIL`
- Similarity: `EXACT_MATCH`, `CONTAINS`, `SEMANTIC_SIMILARITY`
- Quality: `COHERENCE`, `RELEVANCE`, `FACTUALITY`, `HELPFULNESS`,
  `GROUNDEDNESS` (n-gram support from context — hallucination),
  `TOOL_USE_SUCCESS` (tool-call success × result-reference)
- Safety: `TOXICITY`, `BIAS`
- Format: `JSON_VALID`, `SCHEMA_VALID`, `LENGTH`
- Extensibility: `CUSTOM`

**EvalResult** — a `@dataclass(frozen=True)` carrying score (0.0-1.0),
pass/fail, reason, expected/actual values, confidence, latency, and
free-form metadata. All evaluators return this shape.

**Evaluator / BaseEvaluator** — the `@runtime_checkable` Protocol.
`async def evaluate(output, expected=None, context=None) -> EvalResult`.
Implement it and your evaluator plugs into `OnlineEvalPipeline`,
`HierarchicalJudge`, `CompositeEvaluator` with zero wiring changes.

Pluggability:
    class MyEvaluator(BaseEvaluator):
        @property
        def metric(self) -> EvalMetric: return EvalMetric.CUSTOM
        async def evaluate(self, output, expected=None, context=None) -> EvalResult:
            ...
            return self._make_result(score=0.85, reason="...")

Then wire via `NodeEvalBinding` into `OnlineEvalPipeline` or by hand
through `RunEvalTool` for one-off grading.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from cemaf.core.defaults import DEFAULT_FREE_LLM_MODEL
from cemaf.core.types import JSON
from cemaf.core.utils import utc_now


class EvalMetric(StrEnum):
    """Standard evaluation metrics."""

    # Binary
    PASS_FAIL = "pass_fail"

    # Similarity
    EXACT_MATCH = "exact_match"
    CONTAINS = "contains"
    SEMANTIC_SIMILARITY = "semantic_similarity"

    # Quality
    COHERENCE = "coherence"
    RELEVANCE = "relevance"
    FACTUALITY = "factuality"
    HELPFULNESS = "helpfulness"
    GROUNDEDNESS = "groundedness"  # Fraction of output tokens/sentences supported by context
    TOOL_USE_SUCCESS = "tool_use_success"  # Did tool calls succeed and get used?

    # Safety
    TOXICITY = "toxicity"
    BIAS = "bias"

    # Format
    JSON_VALID = "json_valid"
    SCHEMA_VALID = "schema_valid"
    LENGTH = "length"

    # Custom
    CUSTOM = "custom"


@dataclass(frozen=True)
class EvalResult:
    """
    Result of an evaluation.

    Contains score, pass/fail, and reasoning.
    """

    metric: EvalMetric
    score: float  # 0.0 to 1.0
    passed: bool

    # Details
    reason: str = ""
    expected: Any = None
    actual: Any = None

    # Confidence
    confidence: float = 1.0  # How confident is the evaluation

    # Timing
    evaluated_at: datetime = field(default_factory=utc_now)
    latency_ms: float = 0.0

    # Additional data
    metadata: JSON = field(default_factory=dict)

    @classmethod
    def passed_result(
        cls,
        metric: EvalMetric,
        score: float = 1.0,
        reason: str = "",
    ) -> EvalResult:
        """Create a passed result."""
        return cls(
            metric=metric,
            score=score,
            passed=True,
            reason=reason,
        )

    @classmethod
    def failed_result(
        cls,
        metric: EvalMetric,
        score: float = 0.0,
        reason: str = "",
        expected: Any = None,
        actual: Any = None,
    ) -> EvalResult:
        """Create a failed result."""
        return cls(
            metric=metric,
            score=score,
            passed=False,
            reason=reason,
            expected=expected,
            actual=actual,
        )


@dataclass(frozen=True)
class EvalContext:
    """Rich context passed to evaluators — preserves structured output and DAG position."""

    output: Any  # Structured output (not stringified)
    node_id: str = ""
    node_type: str = ""
    dag_name: str = ""
    dag_position: int = 0  # Index in topological order
    dag_total_nodes: int = 0
    previous_scores: tuple[float, ...] = ()  # Scores from prior checkpoints
    metadata: JSON = field(default_factory=dict)

    @property
    def output_as_str(self) -> str:
        """Fallback string representation for evaluators that need it."""
        if isinstance(self.output, str):
            return self.output
        import json

        try:
            return json.dumps(self.output, default=str)
        except (TypeError, ValueError):
            return str(self.output)


class EvalConfig(BaseModel):
    """Configuration for evaluation."""

    model_config = {"frozen": True}

    # Thresholds
    pass_threshold: float = 0.5  # Score >= this = pass

    # Behavior
    fail_fast: bool = False  # Stop on first failure
    include_reasoning: bool = True  # Generate explanations

    # For LLM-based evals
    llm_model: str = DEFAULT_FREE_LLM_MODEL
    max_tokens: int = 1000
    temperature: float = 0.0  # Deterministic


@runtime_checkable
class Evaluator(Protocol):
    """
    Protocol for evaluators.

    Implement for different evaluation strategies:
    - Exact match
    - Semantic similarity
    - LLM-as-judge
    - Custom rules
    """

    @property
    def metric(self) -> EvalMetric:
        """The metric this evaluator measures."""
        ...

    @property
    def name(self) -> str:
        """Human-readable name."""
        ...

    async def evaluate(
        self,
        output: Any,
        expected: Any | None = None,
        context: JSON | None = None,
    ) -> EvalResult:
        """
        Evaluate an output.

        Args:
            output: The output to evaluate
            expected: Expected output (if applicable)
            context: Additional context for evaluation

        Returns:
            EvalResult with score and pass/fail
        """
        ...


class BaseEvaluator(ABC):
    """
    Base class for evaluators.

    Provides common functionality.
    """

    def __init__(
        self,
        config: EvalConfig | None = None,
        name: str | None = None,
    ) -> None:
        self._config = config or EvalConfig()
        self._name = name or self.__class__.__name__

    @property
    @abstractmethod
    def metric(self) -> EvalMetric:
        """The metric this evaluator measures."""
        ...

    @property
    def name(self) -> str:
        """Human-readable name."""
        return self._name

    @property
    def config(self) -> EvalConfig:
        """Evaluator configuration."""
        return self._config

    @abstractmethod
    async def evaluate(
        self,
        output: Any,
        expected: Any | None = None,
        context: JSON | None = None,
    ) -> EvalResult:
        """Evaluate an output."""
        ...

    def _make_result(
        self,
        score: float,
        reason: str = "",
        expected: Any = None,
        actual: Any = None,
        confidence: float = 1.0,
    ) -> EvalResult:
        """Helper to create EvalResult."""
        return EvalResult(
            metric=self.metric,
            score=score,
            passed=score >= self._config.pass_threshold,
            reason=reason,
            expected=expected,
            actual=actual,
            confidence=confidence,
        )
