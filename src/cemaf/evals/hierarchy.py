"""Hierarchical multi-tier evaluation -- fast checks first, expensive judges last."""

import random
from dataclasses import dataclass
from typing import Any

from cemaf.core.types import JSON
from cemaf.evals.composite import CompositeEvaluator
from cemaf.evals.protocols import (
    BaseEvaluator,
    EvalConfig,
    EvalMetric,
    EvalResult,
    Evaluator,
)
from cemaf.observability import get_logger

logger = get_logger("evals.hierarchy")


@dataclass(frozen=True)
class TierResult:
    """Result from a single evaluation tier."""

    tier: int
    score: float
    passed: bool
    escalated: bool


@dataclass(frozen=True)
class HierarchicalJudgeConfig:
    """Configuration for the hierarchical judge."""

    tier1_pass_threshold: float = 0.5
    tier3_ambiguity_range: tuple[float, float] = (0.4, 0.7)
    tier3_sample_rate: float = 0.0


class HierarchicalJudge(BaseEvaluator):
    """Multi-tier evaluator: fast deterministic -> semantic -> LLM judge."""

    def __init__(
        self,
        *,
        tier1_evaluators: tuple[Evaluator, ...],
        tier2_evaluator: Evaluator | None = None,
        tier3_evaluator: Evaluator | None = None,
        config: HierarchicalJudgeConfig | None = None,
    ) -> None:
        tier1_threshold = config.tier1_pass_threshold if config else 0.5
        eval_config = EvalConfig(pass_threshold=tier1_threshold)
        super().__init__(config=eval_config, name="HierarchicalJudge")
        self._tier1 = tier1_evaluators
        self._tier2 = tier2_evaluator
        self._tier3 = tier3_evaluator
        self._hconfig = config or HierarchicalJudgeConfig()

    @property
    def metric(self) -> EvalMetric:
        return EvalMetric.CUSTOM

    async def evaluate(
        self,
        output: Any,
        expected: Any | None = None,
        context: JSON | None = None,
    ) -> EvalResult:
        """Run tiered evaluation, escalating only when needed."""
        tiers_run: list[int] = []
        tier_scores: list[float] = []
        ctx = context or {}

        # --- Tier 1: deterministic checks (always runs) ---
        tier1_result = await self._run_tier1(
            output=output,
            expected=expected,
            context=ctx,
        )
        tiers_run.append(1)
        tier_scores.append(tier1_result.score)

        if not tier1_result.passed:
            logger.debug("Tier 1 failed, skipping higher tiers", score=tier1_result.score)
            return EvalResult(
                metric=self.metric,
                score=tier1_result.score,
                passed=False,
                reason=f"Tier 1 failed (score={tier1_result.score:.2f})",
                expected=expected,
                actual=output,
                metadata={"tiers_run": tiers_run, "tier_scores": tier_scores},
            )

        # --- Tier 2: semantic similarity (if configured) ---
        if self._tier2 is None:
            return EvalResult(
                metric=self.metric,
                score=tier1_result.score,
                passed=True,
                reason="Tier 1 passed, no tier 2 configured",
                expected=expected,
                actual=output,
                metadata={"tiers_run": tiers_run, "tier_scores": tier_scores},
            )

        tier2_result = await self._tier2.evaluate(
            output=output,
            expected=expected,
            context=ctx,
        )
        tiers_run.append(2)
        tier_scores.append(tier2_result.score)

        low, high = self._hconfig.tier3_ambiguity_range
        is_ambiguous = low <= tier2_result.score <= high
        should_sample = random.random() < self._hconfig.tier3_sample_rate  # noqa: S311  # nosec B311

        # --- Tier 3: LLM judge (if ambiguous or sampled) ---
        if self._tier3 is not None and (is_ambiguous or should_sample):
            tier3_result = await self._tier3.evaluate(
                output=output,
                expected=expected,
                context=ctx,
            )
            tiers_run.append(3)
            tier_scores.append(tier3_result.score)

            return EvalResult(
                metric=self.metric,
                score=tier3_result.score,
                passed=tier3_result.passed,
                reason=tier3_result.reason or f"Tier 3 judge: score={tier3_result.score:.2f}",
                expected=expected,
                actual=output,
                confidence=tier3_result.confidence,
                metadata={"tiers_run": tiers_run, "tier_scores": tier_scores},
            )

        # Return tier 2 result
        return EvalResult(
            metric=self.metric,
            score=tier2_result.score,
            passed=tier2_result.passed,
            reason=tier2_result.reason or f"Tier 2: score={tier2_result.score:.2f}",
            expected=expected,
            actual=output,
            confidence=tier2_result.confidence,
            metadata={"tiers_run": tiers_run, "tier_scores": tier_scores},
        )

    async def _run_tier1(
        self,
        *,
        output: Any,
        expected: Any | None,
        context: JSON,
    ) -> EvalResult:
        """Run tier-1 evaluators via CompositeEvaluator."""
        composite = CompositeEvaluator(
            evaluators=list(self._tier1),
            config=EvalConfig(pass_threshold=self._hconfig.tier1_pass_threshold),
        )
        composite_result = await composite.evaluate(
            output=output,
            expected=expected,
            context=context,
        )
        return EvalResult(
            metric=EvalMetric.CUSTOM,
            score=composite_result.overall_score,
            passed=composite_result.overall_passed,
            reason=f"Tier 1: {len(self._tier1)} evaluators",
        )
