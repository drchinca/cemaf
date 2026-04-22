"""Eval tools -- wrap the eval system as CEMAF tools for dogfooding."""

from typing import Any

from cemaf.core.result import Result
from cemaf.core.types import ToolID
from cemaf.evals.composite import CompositeEvaluator
from cemaf.evals.evaluators import (
    ContainsEvaluator,
    ExactMatchEvaluator,
    JSONSchemaEvaluator,
    LengthEvaluator,
)
from cemaf.evals.police import QualityPolice
from cemaf.evals.protocols import Evaluator
from cemaf.tools.base import Tool, ToolResult, ToolSchema

BUILTIN_EVALUATORS: dict[str, type[Evaluator]] = {
    "length": LengthEvaluator,
    "exact_match": ExactMatchEvaluator,
    "contains": ContainsEvaluator,
    "json_valid": JSONSchemaEvaluator,
}


def resolve_evaluators(names: list[str]) -> list[Evaluator]:
    """Instantiate evaluators by name from the built-in registry."""
    evaluators: list[Evaluator] = []
    for name in names:
        cls = BUILTIN_EVALUATORS.get(name)
        if cls is None:
            raise ValueError(f"Unknown evaluator: {name!r}. Available: {sorted(BUILTIN_EVALUATORS)}")
        evaluators.append(cls())
    return evaluators


class RunEvalTool(Tool):
    """Run a set of evaluators on given output text."""

    @property
    def id(self) -> ToolID:
        return ToolID("run_eval")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="run_eval",
            description="Run evaluators on output text",
            parameters={
                "type": "object",
                "properties": {
                    "output": {"type": "string", "description": "Text to evaluate"},
                    "expected": {"type": "string", "description": "Expected output for comparison"},
                    "evaluator_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Evaluator names: length, exact_match, contains, json_valid",
                    },
                },
            },
            required=("output",),
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Run evaluators and return composite result dict."""
        try:
            output: str = kwargs["output"]
            expected: str | None = kwargs.get("expected")
            evaluator_names: list[str] = kwargs.get("evaluator_names", ["length", "json_valid"])

            evaluators = resolve_evaluators(names=evaluator_names)
            composite = CompositeEvaluator(evaluators=evaluators)
            result = await composite.evaluate(output=output, expected=expected)
            return Result.ok(data=result.to_dict())
        except Exception as e:
            return Result.fail(error=str(e))


class CheckQualityTool(Tool):
    """Check the current quality police status."""

    def __init__(self, *, quality_police: QualityPolice) -> None:
        self._police = quality_police

    @property
    def id(self) -> ToolID:
        return ToolID("check_quality")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="check_quality",
            description="Check current quality monitoring status",
            parameters={"type": "object", "properties": {}},
            required=(),
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Return quality police status dict."""
        try:
            alerts = self._police.alerts
            recent_alerts = [
                {
                    "level": a.level.value,
                    "score": a.score,
                    "rolling_mean": a.rolling_mean,
                    "message": a.message,
                    "node_id": a.node_id,
                }
                for a in alerts[-5:]
            ]
            return Result.ok(
                data={
                    "rolling_mean": self._police.rolling_mean,
                    "halted": self._police.should_halt(),
                    "alerts_count": len(alerts),
                    "recent_alerts": recent_alerts,
                }
            )
        except Exception as e:
            return Result.fail(error=str(e))


class RecordScoreTool(Tool):
    """Record a score to the quality police."""

    def __init__(self, *, quality_police: QualityPolice) -> None:
        self._police = quality_police

    @property
    def id(self) -> ToolID:
        return ToolID("record_score")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="record_score",
            description="Record an eval score to quality monitoring",
            parameters={
                "type": "object",
                "properties": {
                    "score": {"type": "number", "description": "Eval score between 0.0 and 1.0"},
                    "node_id": {"type": "string", "description": "Optional node identifier"},
                },
            },
            required=("score",),
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Record score and return alert info if threshold breached."""
        try:
            score: float = float(kwargs["score"])
            node_id: str | None = kwargs.get("node_id")

            alert = self._police.record_score(score=score, node_id=node_id)
            result_dict: dict[str, Any] = {
                "score_recorded": score,
                "rolling_mean": self._police.rolling_mean,
                "halted": self._police.should_halt(),
            }
            if alert is not None:
                result_dict["alert"] = {
                    "level": alert.level.value,
                    "score": alert.score,
                    "rolling_mean": alert.rolling_mean,
                    "message": alert.message,
                    "node_id": alert.node_id,
                }
            return Result.ok(data=result_dict)
        except Exception as e:
            return Result.fail(error=str(e))
