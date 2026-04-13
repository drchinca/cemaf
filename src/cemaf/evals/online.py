"""Online evaluation pipeline — runs evaluators at DAG checkpoints during execution."""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from cemaf.evals.composite import CompositeEvaluator
from cemaf.evals.protocols import EvalContext, Evaluator
from cemaf.events.protocols import Event, EventBus, EventType
from cemaf.observability import get_logger

logger = get_logger("evals.online")


class EvalMode(str, Enum):
    """How to handle eval failures."""

    GATE = "gate"  # Failed eval blocks downstream
    OBSERVE = "observe"  # Log only, don't block


class EvalTrigger(str, Enum):
    """When eval fires."""

    EVERY_NODE = "every_node"  # Legacy: fire after every node
    CHECKPOINT_ONLY = "checkpoint_only"  # Fire only at CHECKPOINT nodes


@dataclass(frozen=True)
class NodeEvalBinding:
    """Binds evaluators to a node pattern."""

    node_pattern: str  # node_id or "*" for all
    evaluators: tuple[Evaluator, ...]
    mode: EvalMode = EvalMode.OBSERVE
    expected: str | None = None
    trigger: EvalTrigger = EvalTrigger.EVERY_NODE


class OnlineEvalPipeline:
    """Subscribes to execution events and runs evaluators on node outputs.

    Supports two modes:
    - EVERY_NODE (legacy): evaluates after each node completes
    - CHECKPOINT_ONLY: evaluates only at explicit CHECKPOINT nodes in the DAG
    """

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
        """Subscribe to execution events."""
        self._event_bus.subscribe(
            event_type=EventType.TASK_COMPLETED,
            handler=self._handle_task_completed,
        )
        self._event_bus.subscribe(
            event_type=EventType.DAG_CHECKPOINT,
            handler=self._handle_checkpoint,
        )

    async def _handle_task_completed(self, event: Event) -> None:
        """Evaluate on TASK_COMPLETED — only for EVERY_NODE bindings."""
        node_id = event.payload.get("node_id", "")
        output = event.payload.get("output")
        if output is None:
            return

        matched = self._find_bindings(
            node_id=node_id,
            trigger=EvalTrigger.EVERY_NODE,
        )
        if not matched:
            return

        eval_ctx = EvalContext(
            output=output,
            node_id=node_id,
            node_type=event.payload.get("node_type", ""),
            dag_name=event.payload.get("dag_name", ""),
            dag_position=event.payload.get("dag_position", 0),
            dag_total_nodes=event.payload.get("dag_total_nodes", 0),
            previous_scores=tuple(r["overall_score"] for r in self._results),
            metadata={"trigger": "task_completed"},
        )

        for binding in matched:
            await self._run_eval(
                binding=binding,
                eval_ctx=eval_ctx,
                correlation_id=event.correlation_id or "",
            )

    async def _handle_checkpoint(self, event: Event) -> None:
        """Evaluate on DAG_CHECKPOINT — for CHECKPOINT_ONLY bindings."""
        node_id = event.payload.get("node_id", "")
        output = event.payload.get("context_snapshot")

        matched = self._find_bindings(
            node_id=node_id,
            trigger=EvalTrigger.CHECKPOINT_ONLY,
        )
        # Also include wildcard EVERY_NODE bindings at checkpoints
        matched.extend(self._find_bindings(node_id=node_id, trigger=EvalTrigger.EVERY_NODE))
        if not matched:
            return

        eval_ctx = EvalContext(
            output=output,
            node_id=node_id,
            node_type="checkpoint",
            dag_name=event.payload.get("dag_name", ""),
            dag_position=event.payload.get("dag_position", 0),
            dag_total_nodes=event.payload.get("dag_total_nodes", 0),
            previous_scores=tuple(r["overall_score"] for r in self._results),
            metadata={"trigger": "checkpoint"},
        )

        for binding in matched:
            await self._run_eval(
                binding=binding,
                eval_ctx=eval_ctx,
                correlation_id=event.correlation_id or "",
            )

    async def _run_eval(
        self,
        *,
        binding: NodeEvalBinding,
        eval_ctx: EvalContext,
        correlation_id: str,
    ) -> None:
        """Run evaluators for a single binding and emit results."""
        await self._event_bus.publish(
            event=Event.create(
                type=EventType.EVAL_STARTED,
                payload={"node_id": eval_ctx.node_id, "mode": binding.mode.value},
                source="online_eval_pipeline",
                correlation_id=correlation_id,
            )
        )

        try:
            composite = CompositeEvaluator(
                evaluators=list(binding.evaluators),
            )
            # Pass structured output — evaluator protocol accepts Any
            result = await composite.evaluate(
                output=eval_ctx.output,
                expected=binding.expected,
                context={
                    "node_id": eval_ctx.node_id,
                    "node_type": eval_ctx.node_type,
                    "dag_name": eval_ctx.dag_name,
                    "dag_position": eval_ctx.dag_position,
                    "trigger": eval_ctx.metadata.get("trigger", ""),
                },
            )

            eval_payload: dict[str, Any] = {
                "node_id": eval_ctx.node_id,
                "mode": binding.mode.value,
                "overall_score": result.overall_score,
                "overall_passed": result.overall_passed,
                "trigger": eval_ctx.metadata.get("trigger", ""),
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
                            "node_id": eval_ctx.node_id,
                            "level": "halt",
                            "score": result.overall_score,
                            "message": (
                                f"Gate eval failed for '{eval_ctx.node_id}'"
                                f" (score={result.overall_score:.2f})"
                            ),
                        },
                        source="online_eval_pipeline",
                        correlation_id=correlation_id,
                    )
                )

            if not result.overall_passed:
                logger.warning(
                    "Eval failed for node '%s': score=%.2f",
                    eval_ctx.node_id,
                    result.overall_score,
                )

        except Exception as e:
            logger.error("Eval pipeline error for node '%s': %s", eval_ctx.node_id, e)
            await self._event_bus.publish(
                event=Event.create(
                    type=EventType.EVAL_FAILED,
                    payload={"node_id": eval_ctx.node_id, "error": str(e)},
                    source="online_eval_pipeline",
                    correlation_id=correlation_id,
                )
            )

    def _find_bindings(
        self,
        *,
        node_id: str,
        trigger: EvalTrigger,
    ) -> list[NodeEvalBinding]:
        """Find bindings matching a node ID and trigger type."""
        return [
            b
            for b in self._bindings
            if b.trigger == trigger and (b.node_pattern == "*" or b.node_pattern == node_id)
        ]

    @property
    def results(self) -> list[dict[str, Any]]:
        """Get accumulated eval results."""
        return list(self._results)
