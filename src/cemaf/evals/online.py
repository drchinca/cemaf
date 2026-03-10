"""Online evaluation pipeline — runs evaluators on node outputs during execution."""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from cemaf.evals.composite import CompositeEvaluator
from cemaf.evals.protocols import Evaluator
from cemaf.events.protocols import Event, EventBus, EventType
from cemaf.observability import get_logger

logger = get_logger("evals.online")


class EvalMode(str, Enum):
    """How to handle eval failures."""

    GATE = "gate"  # Failed eval blocks downstream
    OBSERVE = "observe"  # Log only, don't block


@dataclass(frozen=True)
class NodeEvalBinding:
    """Binds evaluators to a node pattern."""

    node_pattern: str  # node_id or "*" for all
    evaluators: tuple[Evaluator, ...]
    mode: EvalMode = EvalMode.OBSERVE
    expected: str | None = None  # optional expected output


class OnlineEvalPipeline:
    """Subscribes to execution events and runs evaluators on node outputs."""

    def __init__(
        self,
        *,
        bindings: tuple[NodeEvalBinding, ...],
        event_bus: EventBus,
    ) -> None:
        self._bindings = bindings
        self._event_bus = event_bus
        self._results: list[dict[str, Any]] = []

    def subscribe(self) -> None:
        """Subscribe to TASK_COMPLETED events on the bus."""
        self._event_bus.subscribe(
            event_type=EventType.TASK_COMPLETED,
            handler=self._handle_task_completed,
        )

    async def _handle_task_completed(self, event: Event) -> None:
        """Evaluate a completed node's output."""
        node_id = event.payload.get("node_id", "")
        output = event.payload.get("output")
        if output is None:
            return

        matched = self._find_bindings(node_id=node_id)
        if not matched:
            return

        for binding in matched:
            await self._run_eval(
                binding=binding,
                node_id=node_id,
                output=str(output),
                correlation_id=event.correlation_id or "",
            )

    async def _run_eval(
        self,
        *,
        binding: NodeEvalBinding,
        node_id: str,
        output: str,
        correlation_id: str,
    ) -> None:
        """Run evaluators for a single binding and emit results."""
        await self._event_bus.publish(
            event=Event.create(
                type=EventType.EVAL_STARTED,
                payload={"node_id": node_id, "mode": binding.mode.value},
                source="online_eval_pipeline",
                correlation_id=correlation_id,
            )
        )

        try:
            composite = CompositeEvaluator(
                evaluators=list(binding.evaluators),
            )
            result = await composite.evaluate(
                output=output,
                expected=binding.expected,
                context={"node_id": node_id},
            )

            eval_payload: dict[str, Any] = {
                "node_id": node_id,
                "mode": binding.mode.value,
                "overall_score": result.overall_score,
                "overall_passed": result.overall_passed,
                "results": [
                    {
                        "metric": r.metric.value,
                        "score": r.score,
                        "passed": r.passed,
                        "reason": r.reason,
                    }
                    for r in result.results
                ],
            }
            self._results.append(eval_payload)

            await self._event_bus.publish(
                event=Event.create(
                    type=EventType.EVAL_COMPLETED,
                    payload=eval_payload,
                    source="online_eval_pipeline",
                    correlation_id=correlation_id,
                )
            )

            if binding.mode == EvalMode.GATE and not result.overall_passed:
                await self._event_bus.publish(
                    event=Event.create(
                        type=EventType.QUALITY_ALERT,
                        payload={
                            "node_id": node_id,
                            "level": "halt",
                            "score": result.overall_score,
                            "message": f"Gate eval failed for '{node_id}' (score={result.overall_score:.2f})",
                        },
                        source="online_eval_pipeline",
                        correlation_id=correlation_id,
                    )
                )

            if not result.overall_passed:
                logger.warning(
                    "Eval failed for node '%s': score=%.2f",
                    node_id,
                    result.overall_score,
                )

        except Exception as e:
            logger.error("Eval pipeline error for node '%s': %s", node_id, e)
            await self._event_bus.publish(
                event=Event.create(
                    type=EventType.EVAL_FAILED,
                    payload={"node_id": node_id, "error": str(e)},
                    source="online_eval_pipeline",
                    correlation_id=correlation_id,
                )
            )

    def _find_bindings(self, *, node_id: str) -> list[NodeEvalBinding]:
        """Find bindings matching a node ID."""
        return [b for b in self._bindings if b.node_pattern == "*" or b.node_pattern == node_id]

    @property
    def results(self) -> list[dict[str, Any]]:
        """Get accumulated eval results."""
        return list(self._results)
