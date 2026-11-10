"""Online evaluation pipeline — runs evaluators on node outputs while a DAG executes."""

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from cemaf.evals.composite import CompositeEvaluator
from cemaf.evals.protocols import EvalContext, Evaluator
from cemaf.events.protocols import Event, EventBus, EventType
from cemaf.observability import get_logger

logger = get_logger("evals.online")

# Cap concurrent OBSERVE eval LLM calls per process (backpressure; GATE stays sequential).
_OBSERVE_EVAL_SEMAPHORE = asyncio.Semaphore(8)


class EvalMode(StrEnum):
    """How to handle eval failures."""

    GATE = "gate"  # Failed eval halts the run (checked directly by DAGExecutor)
    OBSERVE = "observe"  # Log only, don't block


class TriggerSource(StrEnum):
    """What prompted an evaluation, as recorded on eval results."""

    TASK_COMPLETED = "task_completed"
    CHECKPOINT = "checkpoint"


class EvalTrigger(StrEnum):
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


@dataclass(frozen=True, slots=True)
class GateFailure:
    """A GATE binding that failed for one node of a run; score is None when the evaluator raised."""

    node_id: str
    score: float | None
    message: str


class OnlineEvalPipeline:
    """Runs evaluators on node outputs during execution.

    OBSERVE bindings run from bus events. GATE bindings run only when DAGExecutor
    calls check_gate(), so a failing gate halts the run with any EventBus. Without
    DAGExecutor, GATE bindings do not run.
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
        self._pending: set[asyncio.Task[None]] = set()

    def _spawn_observe(self, coro: Any) -> None:
        """Schedule a fire-and-forget OBSERVE eval and track it for flush()."""
        task = asyncio.create_task(coro)
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def flush(self) -> None:
        """Await all in-flight OBSERVE evals. Production: graceful shutdown. Tests: determinism."""
        if not self._pending:
            return
        in_flight = tuple(self._pending)
        await asyncio.gather(*in_flight, return_exceptions=True)

    async def check_gate(
        self,
        *,
        node_id: str,
        output: object,
        trigger: EvalTrigger,
        run_id: str,
        dag_name: str,
        workspace_id: str | None,
    ) -> GateFailure | None:
        """Run the GATE bindings for a node and return the first failure, if any."""
        matched = self._bindings_in_mode(node_id=node_id, trigger=trigger, mode=EvalMode.GATE)
        if not matched or output is None:
            return None
        source = (
            TriggerSource.CHECKPOINT
            if trigger == EvalTrigger.CHECKPOINT_ONLY
            else TriggerSource.TASK_COMPLETED
        )
        eval_ctx = self._build_eval_context(node_id=node_id, output=output, source=source, dag_name=dag_name)
        for binding in matched:
            failure = await self._run_eval(
                binding=binding,
                eval_ctx=eval_ctx,
                correlation_id=run_id,
                run_id=run_id,
                workspace_id=workspace_id,
            )
            if failure is not None:
                return failure
        return None

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
        payload = event.payload if isinstance(event.payload, dict) else {}
        node_id = str(payload.get("node_id", ""))
        output = payload.get("output")
        if output is None:
            return

        matched = self._bindings_in_mode(
            node_id=node_id, trigger=EvalTrigger.EVERY_NODE, mode=EvalMode.OBSERVE
        )
        if not matched:
            return

        run_id_payload = payload.get("run_id")
        run_id_str = str(run_id_payload) if run_id_payload is not None else (event.correlation_id or "")
        workspace_raw = payload.get("workspace_id")
        workspace_id = str(workspace_raw) if workspace_raw is not None else None

        eval_ctx = self._build_eval_context(
            node_id=node_id,
            output=output,
            source=TriggerSource.TASK_COMPLETED,
            dag_name=str(payload.get("dag_name", "")),
            dag_position=int(payload.get("dag_position", 0)),
            dag_total_nodes=int(payload.get("dag_total_nodes", 0)),
        )

        for binding in matched:
            if binding.mode == EvalMode.OBSERVE:

                async def _observe_run(
                    b: NodeEvalBinding = binding,
                    ctx: EvalContext = eval_ctx,
                    corr: str = event.correlation_id or "",
                    rid: str = run_id_str,
                    ws: str | None = workspace_id,
                ) -> None:
                    async with _OBSERVE_EVAL_SEMAPHORE:
                        await self._run_eval(
                            binding=b,
                            eval_ctx=ctx,
                            correlation_id=corr,
                            run_id=rid,
                            workspace_id=ws,
                        )

                self._spawn_observe(_observe_run())

    async def _handle_checkpoint(self, event: Event) -> None:
        """Evaluate on DAG_CHECKPOINT — for CHECKPOINT_ONLY bindings."""
        payload = event.payload if isinstance(event.payload, dict) else {}
        node_id = str(payload.get("node_id", ""))
        output = payload.get("context_snapshot")

        matched = self._bindings_in_mode(
            node_id=node_id, trigger=EvalTrigger.CHECKPOINT_ONLY, mode=EvalMode.OBSERVE
        )
        # Also include wildcard EVERY_NODE bindings at checkpoints
        matched.extend(
            self._bindings_in_mode(node_id=node_id, trigger=EvalTrigger.EVERY_NODE, mode=EvalMode.OBSERVE)
        )
        if not matched:
            return

        ws_payload = payload.get("workspace_id")
        workspace_id: str | None = str(ws_payload) if ws_payload is not None else None
        if workspace_id is None:
            snapshot = payload.get("context_snapshot")
            if isinstance(snapshot, dict):
                w = snapshot.get("workspace_id")
                if w is not None:
                    workspace_id = str(w)
        run_id_payload = payload.get("run_id")
        run_id_str = str(run_id_payload) if run_id_payload is not None else (event.correlation_id or "")

        eval_ctx = self._build_eval_context(
            node_id=node_id,
            output=output,
            source=TriggerSource.CHECKPOINT,
            dag_name=str(payload.get("dag_name", "")),
            dag_position=int(payload.get("dag_position", 0)),
            dag_total_nodes=int(payload.get("dag_total_nodes", 0)),
        )

        for binding in matched:
            if binding.mode == EvalMode.OBSERVE:

                async def _observe_ckpt(
                    b: NodeEvalBinding = binding,
                    ctx: EvalContext = eval_ctx,
                    corr: str = event.correlation_id or "",
                    rid: str = run_id_str,
                    ws: str | None = workspace_id,
                ) -> None:
                    async with _OBSERVE_EVAL_SEMAPHORE:
                        await self._run_eval(
                            binding=b,
                            eval_ctx=ctx,
                            correlation_id=corr,
                            run_id=rid,
                            workspace_id=ws,
                        )

                self._spawn_observe(_observe_ckpt())

    async def _run_eval(
        self,
        *,
        binding: NodeEvalBinding,
        eval_ctx: EvalContext,
        correlation_id: str,
        run_id: str = "",
        workspace_id: str | None = None,
    ) -> GateFailure | None:
        """Run evaluators for a single binding, emit results, and return a GATE failure if any."""
        eval_scope = {
            "node_id": eval_ctx.node_id,
            "mode": binding.mode.value,
            "run_id": run_id or correlation_id,
            "workspace_id": workspace_id,
        }
        await self._event_bus.publish(
            event=Event.create(
                type=EventType.EVAL_STARTED,
                payload=eval_scope,
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
                "run_id": run_id or correlation_id,
                "workspace_id": workspace_id,
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
                gate_message = f"Gate eval failed for '{eval_ctx.node_id}' (score={result.overall_score:.2f})"
                await self._event_bus.publish(
                    event=Event.create(
                        type=EventType.QUALITY_ALERT,
                        payload={
                            "node_id": eval_ctx.node_id,
                            "level": "halt",
                            "score": result.overall_score,
                            "message": gate_message,
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
            if binding.mode == EvalMode.GATE and not result.overall_passed:
                return GateFailure(
                    node_id=eval_ctx.node_id,
                    score=result.overall_score,
                    message=gate_message,
                )
            return None

        except Exception as e:
            logger.error("Eval pipeline error for node '%s': %s", eval_ctx.node_id, e)
            await self._event_bus.publish(
                event=Event.create(
                    type=EventType.EVAL_FAILED,
                    payload={
                        "node_id": eval_ctx.node_id,
                        "error": str(e),
                        "run_id": run_id or correlation_id,
                        "workspace_id": workspace_id,
                    },
                    source="online_eval_pipeline",
                    correlation_id=correlation_id,
                )
            )
            if binding.mode == EvalMode.GATE:
                return GateFailure(
                    node_id=eval_ctx.node_id,
                    score=None,
                    message=f"Gate eval errored for '{eval_ctx.node_id}': {e}",
                )
            return None

    def _build_eval_context(
        self,
        *,
        node_id: str,
        output: object,
        source: TriggerSource,
        dag_name: str,
        dag_position: int = 0,
        dag_total_nodes: int = 0,
    ) -> EvalContext:
        """Evaluation context for one node output, carrying the scores seen so far."""
        return EvalContext(
            output=output,
            node_id=node_id,
            node_type="checkpoint" if source == TriggerSource.CHECKPOINT else "",
            dag_name=dag_name,
            dag_position=dag_position,
            dag_total_nodes=dag_total_nodes,
            previous_scores=tuple(r["overall_score"] for r in self._results),
            metadata={"trigger": source.value},
        )

    def _bindings_in_mode(
        self,
        *,
        node_id: str,
        trigger: EvalTrigger,
        mode: EvalMode,
    ) -> list[NodeEvalBinding]:
        """Bindings for a node in one mode; GATE bindings run only through check_gate()."""
        return [b for b in self._find_bindings(node_id=node_id, trigger=trigger) if b.mode == mode]

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
