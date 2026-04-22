"""Quality guard agent -- dogfoods CEMAF agent framework for quality monitoring."""

from typing import Any

from pydantic import BaseModel, Field

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.core.enums import AgentStatus
from cemaf.core.types import AgentID
from cemaf.evals.composite import CompositeEvaluator
from cemaf.evals.police import QualityPolice
from cemaf.evals.tools import resolve_evaluators
from cemaf.skills.base import Skill


class QualityGuardGoal(BaseModel):
    """Goal for the quality guard agent."""

    model_config = {"frozen": True}

    output: str = Field(description="Text to evaluate")
    expected: str | None = Field(default=None, description="Expected text for comparison")
    evaluator_names: tuple[str, ...] = Field(
        default=("length", "json_valid"),
        description="Evaluator names to run",
    )
    record_to_police: bool = Field(
        default=True,
        description="Whether to record score to quality police",
    )


class QualityGuardResult(BaseModel):
    """Result of quality guard evaluation."""

    model_config = {"frozen": True}

    passed: bool
    overall_score: float
    quality_status: dict[str, Any]
    alert: dict[str, Any] | None = None


class QualityGuardAgent(Agent[QualityGuardGoal, QualityGuardResult]):
    """Evaluates outputs and monitors quality trends."""

    def __init__(self, *, quality_police: QualityPolice) -> None:
        self._police = quality_police

    @property
    def id(self) -> AgentID:
        return AgentID("QualityGuard")

    @property
    def description(self) -> str:
        return "Evaluates outputs and monitors quality trends"

    @property
    def skills(self) -> tuple[Skill[Any, Any], ...]:
        return ()

    async def run(
        self,
        goal: QualityGuardGoal,
        context: AgentContext,
    ) -> AgentResult[QualityGuardResult]:
        """Run evaluators, optionally record to police, return result."""
        state = AgentState(status=AgentStatus.RUNNING, iteration=1)

        try:
            evaluators = resolve_evaluators(names=list(goal.evaluator_names))
            composite = CompositeEvaluator(evaluators=evaluators)
            eval_result = await composite.evaluate(
                output=goal.output,
                expected=goal.expected,
            )

            alert_dict: dict[str, Any] | None = None
            if goal.record_to_police:
                alert = self._police.record_score(score=eval_result.overall_score)
                if alert is not None:
                    alert_dict = {
                        "level": alert.level.value,
                        "score": alert.score,
                        "rolling_mean": alert.rolling_mean,
                        "message": alert.message,
                        "node_id": alert.node_id,
                    }

            quality_status = self._police.to_dict()

            result = QualityGuardResult(
                passed=eval_result.overall_passed,
                overall_score=eval_result.overall_score,
                quality_status=quality_status,
                alert=alert_dict,
            )

            final_state = state.next(status=AgentStatus.COMPLETED)
            return AgentResult.ok(output=result, state=final_state)

        except Exception as e:
            final_state = state.next(status=AgentStatus.FAILED)
            return AgentResult.fail(error=str(e), state=final_state)
