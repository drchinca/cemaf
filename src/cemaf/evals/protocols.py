"""
Evaluation protocols - Abstract interfaces for output evaluation.

Supports:
- Pass/fail evaluation
- Numeric scoring
- Multi-metric evaluation
- Confidence scores
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from cemaf.core.types import JSON
from cemaf.core.utils import utc_now


class EvalMetric(str, Enum):
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


class EvalConfig(BaseModel):
    """Configuration for evaluation."""

    model_config = {"frozen": True}

    # Thresholds
    pass_threshold: float = 0.5  # Score >= this = pass

    # Behavior
    fail_fast: bool = False  # Stop on first failure
    include_reasoning: bool = True  # Generate explanations

    # For LLM-based evals
    llm_model: str = "gpt-4"
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
