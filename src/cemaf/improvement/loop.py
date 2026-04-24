"""
SelfImprovementLoop: Connects CEMAF audit → eval → strategy update.

After each DAG execution:
1. Score quality (cost, latency, error rate, success)
2. Update StrategyMemory with the outcome
3. Update TrustLedger for each tool/skill used
4. Flag underperforming dynamic tools for regeneration (via insights list)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from cemaf.core.result import Result
from cemaf.core.types import JSON
from cemaf.memory.strategy import StrategyMemory
from cemaf.trust.ledger import TrustLedger

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImprovementOutcome:
    """Summary of what the self-improvement loop did on a single run."""

    run_id: str
    quality_score: float            # 0.0 – 1.0
    strategies_updated: int
    tools_promoted: int
    tools_deprecated: int
    insights: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExecutionSummary:
    """Lightweight summary of a DAG execution for improvement analysis.

    Callers should populate ``tool_executions`` with one dict per tool call:
    ``{"tool_id": str, "success": bool, "latency_ms": float}``
    """

    run_id: str
    task_description: str
    approach: str                   # Which strategy / plan was used
    success: bool
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    latency_ms: float = 0.0
    error_count: int = 0
    tool_executions: list[dict[str, Any]] = field(default_factory=list)
    metadata: JSON = field(default_factory=dict)


class SelfImprovementLoop:
    """
    Post-execution learning loop.

    Instantiate once and call ``process(summary)`` after every DAG run.
    Both ``StrategyMemory`` and ``TrustLedger`` are updated in-place.
    """

    def __init__(
        self,
        strategy_memory: StrategyMemory,
        trust_ledger: TrustLedger,
        *,
        quality_threshold: float = 0.6,
    ) -> None:
        self._strategy_memory = strategy_memory
        self._trust_ledger = trust_ledger
        self._quality_threshold = quality_threshold

    async def process(
        self, summary: ExecutionSummary
    ) -> Result[ImprovementOutcome]:
        """Process a completed execution and update all learning systems."""
        try:
            quality = self._score_quality(summary)
            insights: list[str] = []

            # 1. Update StrategyMemory
            await self._strategy_memory.record_outcome(
                task_pattern=summary.task_description,
                approach=summary.approach,
                success=summary.success,
                quality=quality,
            )
            insights.append(f"Strategy recorded (quality={quality:.2f})")

            # 2. Update TrustLedger for each tool used
            promoted = 0
            deprecated = 0
            for tool_exec in summary.tool_executions:
                tool_id = str(tool_exec.get("tool_id", "unknown"))
                exec_success = bool(tool_exec.get("success", False))
                latency = float(tool_exec.get("latency_ms", 0.0))

                before = self._trust_ledger.get(tool_id)
                entry = self._trust_ledger.record(
                    tool_id,
                    "tool",
                    success=exec_success,
                    latency_ms=latency,
                )

                if before and before.trust_level != entry.trust_level:
                    if entry.trust_level.value == "trusted":
                        promoted += 1
                        insights.append(f"Tool {tool_id} promoted to TRUSTED")
                    elif entry.trust_level.value == "deprecated":
                        deprecated += 1
                        insights.append(
                            f"Tool {tool_id} DEPRECATED after failures"
                        )

            # 3. Log quality warnings
            if quality < self._quality_threshold and summary.success:
                insights.append(
                    f"Low quality score ({quality:.2f}) despite success — "
                    "consider optimising token usage or approach"
                )

            if not summary.success:
                insights.append(
                    f"Execution failed. Approach '{summary.approach}' "
                    "penalised in strategy memory."
                )

            outcome = ImprovementOutcome(
                run_id=summary.run_id,
                quality_score=quality,
                strategies_updated=1,
                tools_promoted=promoted,
                tools_deprecated=deprecated,
                insights=insights,
            )

            logger.info(
                "SelfImprovementLoop: run=%s quality=%.2f insights=%d",
                summary.run_id,
                quality,
                len(insights),
            )
            return Result.ok(outcome)

        except Exception as e:
            logger.error("SelfImprovementLoop failed: %s", e, exc_info=True)
            return Result.fail(str(e))

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_quality(self, summary: ExecutionSummary) -> float:
        """Composite quality score from execution metrics.

        Weights:
          - Success:          40 %
          - Low error rate:   20 %
          - Token efficiency: 20 %  (penalises > 100 k tokens)
          - Latency:          20 %  (penalises > 60 s)
        """
        score = 0.0

        # Success component (40 %)
        score += 0.4 if summary.success else 0.0

        # Error rate component (20 %)
        tool_count = max(1, len(summary.tool_executions))
        error_rate = summary.error_count / tool_count
        score += 0.2 * max(0.0, 1.0 - error_rate)

        # Token efficiency (20 %) — penalise > 100 k tokens
        token_score = max(0.0, 1.0 - summary.total_tokens / 100_000)
        score += 0.2 * token_score

        # Latency (20 %) — penalise > 60 s
        latency_score = max(0.0, 1.0 - summary.latency_ms / 60_000)
        score += 0.2 * latency_score

        return round(min(1.0, max(0.0, score)), 4)
