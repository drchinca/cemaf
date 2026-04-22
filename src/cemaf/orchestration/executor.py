"""
DAG Executor - Runs DAGs with parallel execution support.

The executor:
- Resolves dependencies via topological sort
- Executes nodes in correct order
- Handles PARALLEL nodes with concurrent execution
- Handles ROUTER nodes with conditional branching
- Manages context propagation
- Provides checkpointing for resume
- Emits context patches for provenance tracking
- Integrates with RunLogger for recording

Note: Uses PEP 563 () to defer annotation evaluation
and avoid circular imports with cemaf.events, cemaf.moderation, and cemaf.observability.
Type imports happen at runtime within methods that need them.
"""

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from cemaf.context.context import Context
from cemaf.context.merge import (
    DEFAULT_MERGE_STRATEGY,
    MergeStrategy,
)
from cemaf.context.patch import ContextPatch, PatchOperation, PatchSource
from cemaf.core.constants import MAX_PARALLEL_NODES
from cemaf.core.enums import NodeType, RunStatus
from cemaf.core.execution import CancellationToken
from cemaf.core.recovery import AutoHealManager
from cemaf.core.types import JSON, NodeID, RunID
from cemaf.core.utils import utc_now
from cemaf.evals.police import QualityPolice
from cemaf.events.protocols import Event, EventBus, EventType
from cemaf.memory.session import SessionManager
from cemaf.moderation.pipeline import ModerationPipeline
from cemaf.observability import get_logger, get_metrics
from cemaf.observability.budget_guard import BudgetGuard
from cemaf.observability.health import HealthMonitor
from cemaf.observability.run_logger import RunLogger
from cemaf.orchestration.dag import DAG, Edge, EdgeCondition, Node
from cemaf.orchestration.dependency_resolver import resolve_node_input
from cemaf.orchestration.node_handlers import (
    NodeHandlerContext,
    execute_conditional_node,
    execute_loop_node,
    execute_parallel_node,
    execute_router_node,
)
from cemaf.orchestration.node_handlers import (
    run_parallel_nodes as _run_parallel_nodes,
)

logger = get_logger("orchestration.executor")
metrics = get_metrics()


# Per-run state lives in ContextVars so a single DAGExecutor instance is
# safe under concurrent run() calls — each async task sees its own run's
# route choices and correlation id without clobbering siblings. Defaults
# are None; run() seeds both on entry via .set() with fresh values.
_route_choices_var: ContextVar[dict[NodeID, set[NodeID]] | None] = ContextVar(
    "cemaf_route_choices",
    default=None,
)
_correlation_id_var: ContextVar[str] = ContextVar(
    "cemaf_correlation_id",
    default="",
)


class HaltReason(str, Enum):
    """Why a DAG execution was halted mid-flight.

    Enum-typed so on-call engineers reading logs at 3am know immediately
    which gate fired — a bare `should_halt=True` with no reason is
    debuggable-pain.
    """

    BUDGET_EXHAUSTED = "budget_exhausted"
    QUALITY_DEGRADED = "quality_degraded"


@dataclass(frozen=True, slots=True)
class HaltSignal:
    """Signal raised by an outer controller to stop mid-flight execution.

    `reason` drives alerting/routing; `detail` is a free-form human hint
    (budget state dict, quality window, etc.) for logs. `source` names
    the component that raised — BudgetGuard, QualityPolice, etc.
    """

    reason: HaltReason
    source: str
    detail: str = ""


def _current_route_choices() -> dict[NodeID, set[NodeID]]:
    """Read-accessor with defensive empty-dict fallback for pre-run reads."""
    choices = _route_choices_var.get()
    if choices is None:
        return {}
    return choices


def _flatten_for_moderation(*, output: Any, max_depth: int = 10) -> str:
    """Extract concatenated string leaves from a possibly nested output.

    str(dict) produces Python repr (`{'key': 'val'}`) which moderation gates
    can't meaningfully parse — the separators and quotes drown out semantic
    content. This walker pulls every string leaf out and joins them with
    newlines so moderation sees the actual language, not the container.
    """
    parts: list[str] = []

    def _walk(value: Any, depth: int) -> None:
        if depth > max_depth:
            return
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            for v in value.values():
                _walk(v, depth + 1)
        elif isinstance(value, (list, tuple, set)):
            for v in value:
                _walk(v, depth + 1)
        elif value is None or isinstance(value, bool):
            return
        else:
            parts.append(str(value))

    _walk(output, 0)
    return "\n".join(parts)


class ExecutorConfig(BaseModel):
    """
    Configuration for DAGExecutor.

    Provides settings for execution behavior, logging, events, and moderation.
    """

    model_config = {"frozen": True}

    max_parallel: int = Field(
        default=MAX_PARALLEL_NODES,
        description="Maximum number of parallel node executions",
    )
    enable_logging: bool = Field(
        default=True,
        description="Enable run logging for replay and debugging",
    )
    enable_events: bool = Field(
        default=True,
        description="Enable event bus integration",
    )
    enable_moderation: bool = Field(
        default=False,
        description="Enable moderation pipeline for content safety",
    )
    merge_strategy: str = Field(
        default="last_write_wins",
        description="Strategy for merging parallel branch contexts: "
        "'last_write_wins', 'raise_on_conflict', 'deep_merge'",
    )
    node_timeout_seconds: float = Field(
        default=300.0,
        description="Per-node execution timeout in seconds",
    )


@dataclass(frozen=True)
class NodeResult:
    """Result of executing a single node."""

    node_id: NodeID
    success: bool
    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    metadata: JSON = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResult:
    """Result of executing an entire DAG."""

    run_id: RunID
    dag_name: str
    status: RunStatus
    node_results: tuple[NodeResult, ...] = field(default_factory=tuple)
    final_context: Context = field(default_factory=Context)  # Updated to Context
    error: str | None = None
    started_at: datetime = field(default_factory=utc_now)
    health_check_metadata: JSON = field(default_factory=dict)  # Health status at execution time
    completed_at: datetime | None = None
    metadata: JSON = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status == RunStatus.COMPLETED

    @property
    def duration_ms(self) -> float:
        if not self.completed_at:
            return 0.0
        delta = self.completed_at - self.started_at
        return delta.total_seconds() * 1000


@runtime_checkable
class NodeExecutor(Protocol):
    """Protocol for executing a node."""

    async def execute_node(
        self,
        node: Node,
        context: Context,  # Updated to Context
    ) -> NodeResult:
        """Execute a single node."""
        ...


class DAGExecutor:
    """
    Executes DAGs with dependency resolution and parallel execution.

    Supports:
    - TOOL/SKILL/AGENT nodes: Sequential execution
    - PARALLEL nodes: Concurrent execution of sub-nodes
    - ROUTER nodes: Conditional branching based on context
    - Edge conditions: ON_SUCCESS, ON_FAILURE, CONDITIONAL
    - Context patch emission for provenance tracking
    - Run logging for replay and debugging

    Usage:
        executor = DAGExecutor(node_executor=my_executor)
        result = await executor.run(dag, initial_context)

        # With logging
        executor = DAGExecutor(
            node_executor=my_executor,
            run_logger=InMemoryRunLogger(),
        )
    """

    def __init__(
        self,
        node_executor: NodeExecutor,
        max_parallel: int = MAX_PARALLEL_NODES,
        run_logger: RunLogger | None = None,
        event_bus: EventBus | None = None,
        moderation_pipeline: ModerationPipeline | None = None,
        merge_strategy: MergeStrategy | None = None,
        health_registry: HealthMonitor | None = None,
        require_healthy: bool = True,
        auto_heal_manager: AutoHealManager | None = None,
        budget_guard: BudgetGuard | None = None,
        session_manager: SessionManager | None = None,
        node_timeout_seconds: float = 300.0,
        quality_police: QualityPolice | None = None,
    ) -> None:
        self._node_executor = node_executor
        self._max_parallel = max_parallel
        self._node_timeout = node_timeout_seconds
        self._run_logger = run_logger
        self._event_bus = event_bus
        self._moderation_pipeline = moderation_pipeline
        self._quality_police = quality_police
        self._merge_strategy = merge_strategy or DEFAULT_MERGE_STRATEGY
        self._health_registry = health_registry
        self._require_healthy = require_healthy
        self._auto_heal_manager = auto_heal_manager
        self._budget_guard = budget_guard
        self._session_manager = session_manager

    def _halt_signal(self) -> HaltSignal | None:
        """Aggregate halt check across all outer controllers.

        Returns the first-firing signal with structured reason + source, so
        logs and alerts carry WHY the DAG stopped. None = keep running.

        Priority: budget (harder stop — you literally can't afford more)
        over quality (soft stop — outputs are degraded).
        """
        if self._budget_guard is not None and self._budget_guard.should_halt():
            return HaltSignal(
                reason=HaltReason.BUDGET_EXHAUSTED,
                source="BudgetGuard",
                detail=str(self._budget_guard.to_dict()),
            )
        if self._quality_police is not None and self._quality_police.should_halt():
            return HaltSignal(
                reason=HaltReason.QUALITY_DEGRADED,
                source="QualityPolice",
                detail=str(self._quality_police.to_dict()),
            )
        return None

    def _should_halt(self) -> bool:
        """Bool adapter over _halt_signal() for the NodeHandlerContext.should_halt callback."""
        return self._halt_signal() is not None

    async def _emit_event(self, event_type: EventType, payload: JSON) -> None:
        """Emit event if bus is configured."""
        if self._event_bus is None:
            return
        event = Event.create(
            type=event_type,
            payload=payload,
            source="dag_executor",
            correlation_id=_correlation_id_var.get(),
        )
        await self._event_bus.publish(event=event)

    async def run(
        self,
        dag: DAG,
        initial_context: Context | None = None,
        run_id: RunID | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> ExecutionResult:
        """Public entry point. Wraps _run_impl in ContextVar reset guard."""
        effective_run_id = run_id or RunID(f"run_{utc_now().isoformat()}")
        route_token = _route_choices_var.set({})
        correlation_token = _correlation_id_var.set(str(effective_run_id))
        try:
            return await self._run_impl(
                dag=dag,
                initial_context=initial_context,
                run_id=effective_run_id,
                cancellation_token=cancellation_token,
            )
        finally:
            # Reset ContextVars so sequential awaits in the same task don't
            # inherit stale state from this run. Task-copy semantics protect
            # concurrent runs; this protects sequential ones.
            _route_choices_var.reset(route_token)
            _correlation_id_var.reset(correlation_token)

    async def _run_impl(
        self,
        dag: DAG,
        initial_context: Context | None = None,
        run_id: RunID | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> ExecutionResult:
        """
        Execute the DAG.

        Args:
            dag: The DAG to execute
            initial_context: Starting context
            run_id: Optional run ID (generated if not provided)

        Returns:
            ExecutionResult with all node results and final context
        """
        # ContextVars were set by the public run() wrapper and will be
        # reset in its finally block. We just read them here.
        run_id = run_id or RunID(f"run_{utc_now().isoformat()}")
        context = initial_context or Context()
        node_results: list[NodeResult] = []
        started_at = utc_now()
        health_check_metadata: JSON = {}

        # Record DAG execution start
        metrics.counter("cemaf.dag.executions.total", tags={"dag_name": dag.name})
        logger.info(
            "Starting DAG execution",
            dag_name=dag.name,
            run_id=str(run_id),
            num_nodes=len(dag.nodes),
        )

        # Start logging if logger is configured
        if self._run_logger:
            self._run_logger.start_run(
                run_id=str(run_id),
                dag_name=dag.name,
                initial_context=context,
            )

        # Emit DAG started event
        await self._emit_event(
            event_type=EventType.DAG_STARTED,
            payload={"dag_name": dag.name, "run_id": str(run_id)},
        )

        # Bootstrap memory session
        if self._session_manager:
            try:
                await self._session_manager.bootstrap(session_id=str(run_id))
            except Exception as e:
                logger.warning("Memory session bootstrap failed: %s", e)

        try:
            # Validate DAG
            dag.validate_structure()
            # Health check - fail-fast if critical dependencies unavailable
            if self._health_registry and self._require_healthy:
                health_result = await self._health_registry.check_all()
                health_check_metadata = health_result.__dict__

                from cemaf.observability.health import HealthStatus

                if health_result.status == HealthStatus.UNHEALTHY:
                    logger.error(
                        "Execution blocked by health check failure",
                        extra={
                            "health_status": health_result.status,
                            "health_message": health_result.message,
                            "dag_name": dag.name,
                            "run_id": str(run_id),
                        },
                    )
                    # Record health check blocking metric
                    metrics.counter(
                        "cemaf.dag.executions.blocked_by_health",
                        tags={"dag_name": dag.name},
                    )
                    # End run logging if started
                    if self._run_logger:
                        self._run_logger.end_run(
                            final_context=context,
                            success=False,
                            error=f"Health check failed: {health_result.message}",
                        )

                    return ExecutionResult(
                        run_id=run_id,
                        dag_name=dag.name,
                        status=RunStatus.FAILED,
                        error=f"Pre-execution health check failed: {health_result.message}",
                        started_at=started_at,
                        completed_at=utc_now(),
                        health_check_metadata=health_check_metadata,
                    )

            # Get execution order
            order = dag.topological_sort()

            # Track completed nodes for edge conditions
            completed: dict[NodeID, NodeResult] = {}

            # Build handler context for node-type dispatchers. route_choices
            # is a dict reference shared with the ContextVar's view; mutations
            # by handlers propagate to readers via the same object.
            # `should_halt` lets inner LOOP handlers poll for outer halts
            # (QualityPolice, BudgetGuard) between iterations so they don't
            # waste N-1 LLM calls after halt fires.
            handler_ctx = NodeHandlerContext(
                route_choices=_current_route_choices(),
                apply_output=self._apply_node_output,
                execute_with_retry=self._execute_with_retry,
                merge_strategy=self._merge_strategy,
                max_parallel=self._max_parallel,
                run_logger=self._run_logger,
                correlation_id=_correlation_id_var.get(),
                should_halt=self._should_halt,
            )

            for node_id in order:
                # Check cancellation before each node
                if cancellation_token and cancellation_token.is_cancelled:
                    cancel_msg = f"Execution cancelled: {cancellation_token.reason}"
                    logger.warning(cancel_msg, dag_name=dag.name, run_id=str(run_id))
                    if self._run_logger:
                        self._run_logger.end_run(
                            final_context=context,
                            success=False,
                            error=cancel_msg,
                        )
                    return ExecutionResult(
                        run_id=run_id,
                        dag_name=dag.name,
                        status=RunStatus.FAILED,
                        node_results=tuple(node_results),
                        final_context=context,
                        error=cancel_msg,
                        started_at=started_at,
                        completed_at=utc_now(),
                        health_check_metadata=health_check_metadata,
                    )

                if node_id in completed:
                    continue

                node = dag.get_node(node_id)
                if not node:
                    continue

                # Check if we should execute this node based on edge conditions
                incoming = dag.get_incoming_edges(node_id)
                should_execute = self._should_execute_node(node, incoming, completed, context)

                if not should_execute:
                    continue

                # Handle different node types
                if node.type == NodeType.PARALLEL:
                    (
                        group_result,
                        parallel_results,
                        new_context,
                    ) = await execute_parallel_node(
                        dag,
                        node,
                        context,
                        handler_ctx=handler_ctx,
                    )
                    context = new_context
                    node_results.append(group_result)
                    completed[node_id] = group_result

                    for parallel_result in parallel_results:
                        node_results.append(parallel_result)
                        completed[parallel_result.node_id] = parallel_result

                    result = group_result

                elif node.type == NodeType.ROUTER:
                    result, new_context = execute_router_node(node, context, handler_ctx=handler_ctx)
                    context = new_context
                    node_results.append(result)
                    completed[node_id] = result

                elif node.type == NodeType.CONDITIONAL:
                    result, new_context = execute_conditional_node(node, context, handler_ctx=handler_ctx)
                    context = new_context
                    node_results.append(result)
                    completed[node_id] = result

                elif node.type == NodeType.LOOP:
                    result, loop_results, new_context = await execute_loop_node(
                        dag,
                        node,
                        context,
                        handler_ctx=handler_ctx,
                    )
                    context = new_context
                    node_results.append(result)
                    completed[node_id] = result
                    for loop_result in loop_results:
                        node_results.append(loop_result)
                    # Mark body nodes as completed so topo sort skips them
                    for body_id in (node.config or {}).get("body_node_ids", []):
                        completed[NodeID(body_id)] = result

                elif node.type == NodeType.CHECKPOINT:
                    # Checkpoint node — emit DAG_CHECKPOINT for eval pipeline
                    checkpoint_result = NodeResult(
                        node_id=node_id,
                        success=True,
                        output={"checkpoint": str(node_id)},
                        duration_ms=0.0,
                    )
                    node_results.append(checkpoint_result)
                    completed[node_id] = checkpoint_result
                    result = checkpoint_result

                    await self._emit_event(
                        event_type=EventType.DAG_CHECKPOINT,
                        payload={
                            "node_id": str(node_id),
                            "dag_name": dag.name,
                            "dag_total_nodes": len(order),
                            "context_snapshot": {k: str(v)[:500] for k, v in context.data.items()},
                        },
                    )

                else:
                    # Standard execution (TOOL, SKILL, AGENT)
                    result, new_context = await self._execute_with_retry(node, context)  # Added new_context
                    context = new_context  # Update context
                    node_results.append(result)
                    completed[node_id] = result

                # Record per-node metrics.
                # We deliberately do NOT include node_id or run_id in tags —
                # those are unbounded cardinality dimensions and will OOM a
                # Prometheus registry within hours of real traffic. node_id and
                # run_id live in structured logs and audit entries where they
                # belong; metrics stay aggregable.
                node_type_name = node.type.value if hasattr(node.type, "value") else str(node.type)
                node_tags = {
                    "node_type": node_type_name,
                    "dag_name": dag.name,
                    "status": "success" if result.success else "failed",
                }
                metrics.counter("cemaf.node.executions.total", tags=node_tags)
                metrics.histogram("cemaf.node.duration_ms", result.duration_ms, tags=node_tags)
                if result.success:
                    metrics.counter("cemaf.node.executions.success", tags=node_tags)
                else:
                    metrics.counter("cemaf.node.executions.failed", tags=node_tags)

                # Emit node completion event
                await self._emit_event(
                    event_type=EventType.TASK_COMPLETED if result.success else EventType.TASK_FAILED,
                    payload={
                        "node_id": str(node_id),
                        "success": result.success,
                        "duration_ms": result.duration_ms,
                        "error": result.error,
                        "output": result.output,
                    },
                )

                # Fire checkpoint event if node has checkpoint marker
                if node.checkpoint_enabled and result.success and node.type != NodeType.CHECKPOINT:
                    await self._emit_event(
                        event_type=EventType.DAG_CHECKPOINT,
                        payload={
                            "node_id": str(node_id),
                            "dag_name": dag.name,
                            "dag_total_nodes": len(order),
                            "context_snapshot": {k: str(v)[:500] for k, v in context.data.items()},
                        },
                    )

                # Post-flight moderation on the node's output. The executor
                # holds the pipeline (previously plumbed but never invoked);
                # if it blocks, the node is rewritten to failed with an
                # explicit violation error, and the DAG cannot pass the tainted
                # output to downstream nodes.
                if self._moderation_pipeline is not None and result.success and result.output is not None:
                    # Flatten structured output to its text leaves before
                    # moderation. str({"summary": "..."}) produces Python repr
                    # which gates read as noise; semantic content lives inside.
                    moderation_result = await self._moderation_pipeline.check_output(
                        content=_flatten_for_moderation(output=result.output),
                        context=context,
                    )
                    if not moderation_result.allowed:
                        violation_codes = [v.code for v in moderation_result.violations]
                        error_msg = (
                            f"Output blocked by moderation (codes: {violation_codes or ['unspecified']})"
                        )
                        logger.warning(
                            "Node output blocked by moderation",
                            node_id=str(node_id),
                            violations=violation_codes,
                        )
                        blocked_metadata = dict(result.metadata or {})
                        blocked_metadata["moderation_blocked"] = True
                        blocked_metadata["moderation_violations"] = violation_codes
                        result = NodeResult(
                            node_id=node_id,
                            success=False,
                            output=None,
                            error=error_msg,
                            duration_ms=result.duration_ms,
                            metadata=blocked_metadata,
                        )
                        # Replace the recorded result so downstream checks see failure.
                        node_results[-1] = result
                        completed[node_id] = result

                # Budget guard halt check after each node. Cost recording
                # itself happens inside _execute_with_retry (see there), so
                # LOOP body iterations also count toward the cap — otherwise
                # a runaway loop could burn its entire cost budget before the
                # outer halt check sees anything.
                if self._budget_guard and result.success and self._budget_guard.should_halt():
                    completed_at = utc_now()
                    duration_ms = (completed_at - started_at).total_seconds() * 1000
                    halt_msg = "Budget exhausted - execution halted"
                    logger.warning(
                        halt_msg,
                        dag_name=dag.name,
                        budget_state=self._budget_guard.to_dict(),
                    )
                    if self._run_logger:
                        self._run_logger.end_run(
                            final_context=context,
                            success=False,
                            error=halt_msg,
                        )
                    return ExecutionResult(
                        run_id=run_id,
                        dag_name=dag.name,
                        status=RunStatus.FAILED,
                        node_results=tuple(node_results),
                        final_context=context,
                        error=halt_msg,
                        started_at=started_at,
                        completed_at=completed_at,
                        health_check_metadata=health_check_metadata,
                        metadata={"budget_guard": self._budget_guard.to_dict()},
                    )

                # Quality police check after each node
                if self._quality_police and self._quality_police.should_halt():
                    completed_at = utc_now()
                    halt_msg = "Quality degradation - execution halted"
                    logger.warning(
                        halt_msg,
                        dag_name=dag.name,
                        quality_state=self._quality_police.to_dict(),
                    )
                    if self._run_logger:
                        self._run_logger.end_run(
                            final_context=context,
                            success=False,
                            error=halt_msg,
                        )
                    return ExecutionResult(
                        run_id=run_id,
                        dag_name=dag.name,
                        status=RunStatus.FAILED,
                        node_results=tuple(node_results),
                        final_context=context,
                        error=halt_msg,
                        started_at=started_at,
                        completed_at=completed_at,
                        health_check_metadata=health_check_metadata,
                    )

                # Stop on failure if retry_on_failure is False
                if not result.success and not node.retry_on_failure and node.type != NodeType.CONDITIONAL:
                    # Record DAG failure metrics
                    completed_at = utc_now()
                    duration_ms = (completed_at - started_at).total_seconds() * 1000
                    error_type = result.metadata.get("error_type", "Unknown") if result.error else "None"
                    failure_tags = {"dag_name": dag.name, "error_type": error_type}
                    metrics.counter("cemaf.dag.executions.failed", tags=failure_tags)
                    metrics.histogram("cemaf.dag.duration_ms", duration_ms, tags=failure_tags)

                    logger.error(
                        "DAG execution failed at node",
                        dag_name=dag.name,
                        failed_node=str(node_id),
                        error=result.error,
                        duration_ms=duration_ms,
                    )

                    # End run logging
                    if self._run_logger:
                        self._run_logger.end_run(
                            final_context=context,
                            success=False,
                            error=result.error,
                        )

                    # Emit DAG failed event
                    await self._emit_event(
                        event_type=EventType.TASK_FAILED,
                        payload={
                            "dag_name": dag.name,
                            "run_id": str(run_id),
                            "failed_node": str(node_id),
                            "error": result.error,
                        },
                    )

                    return ExecutionResult(
                        run_id=run_id,
                        dag_name=dag.name,
                        status=RunStatus.FAILED,
                        node_results=tuple(node_results),
                        final_context=context,
                        error=result.error,
                        started_at=started_at,
                        completed_at=completed_at,
                        health_check_metadata=health_check_metadata,
                    )

            # End run logging - success
            if self._run_logger:
                self._run_logger.end_run(
                    final_context=context,
                    success=True,
                )

            # Record DAG success metrics
            completed_at = utc_now()
            duration_ms = (completed_at - started_at).total_seconds() * 1000
            success_tags = {"dag_name": dag.name, "status": "completed"}
            metrics.counter("cemaf.dag.executions.completed", tags=success_tags)
            metrics.histogram("cemaf.dag.duration_ms", duration_ms, tags=success_tags)
            metrics.gauge(
                "cemaf.dag.nodes.completed",
                len(node_results),
                tags={"dag_name": dag.name},
            )

            logger.info(
                "DAG execution completed successfully",
                dag_name=dag.name,
                run_id=str(run_id),
                num_nodes=len(node_results),
                duration_ms=duration_ms,
            )

            # Emit DAG completed event
            await self._emit_event(
                event_type=EventType.DAG_COMPLETED,
                payload={
                    "dag_name": dag.name,
                    "run_id": str(run_id),
                    "num_nodes": len(node_results),
                    "duration_ms": duration_ms,
                },
            )

            return ExecutionResult(
                run_id=run_id,
                dag_name=dag.name,
                status=RunStatus.COMPLETED,
                node_results=tuple(node_results),
                final_context=context,
                started_at=started_at,
                completed_at=completed_at,
                health_check_metadata=health_check_metadata,
            )

        except Exception as e:
            # End run logging - exception
            if self._run_logger:
                self._run_logger.end_run(
                    final_context=context,
                    success=False,
                    error=str(e),
                )

            # Record DAG exception metrics
            completed_at = utc_now()
            duration_ms = (completed_at - started_at).total_seconds() * 1000
            error_type = type(e).__name__
            exception_tags = {"dag_name": dag.name, "error_type": error_type}
            metrics.counter("cemaf.dag.executions.failed", tags=exception_tags)
            metrics.histogram("cemaf.dag.duration_ms", duration_ms, tags=exception_tags)

            logger.error(
                "DAG execution failed with exception",
                dag_name=dag.name,
                run_id=str(run_id),
                error=str(e),
                error_type=error_type,
                duration_ms=duration_ms,
                exc_info=True,
            )

            # Emit DAG failed event (exception path)
            await self._emit_event(
                event_type=EventType.SYSTEM_ERROR,
                payload={
                    "dag_name": dag.name,
                    "run_id": str(run_id),
                    "error": str(e),
                    "error_type": error_type,
                },
            )

            return ExecutionResult(
                run_id=run_id,
                dag_name=dag.name,
                status=RunStatus.FAILED,
                node_results=tuple(node_results),
                final_context=context,
                error=str(e),
                started_at=started_at,
                completed_at=completed_at,
                health_check_metadata=health_check_metadata,
            )

        finally:
            # Dispose memory session regardless of outcome
            if self._session_manager:
                try:
                    await self._session_manager.dispose(session_id=str(run_id))
                except Exception as e:
                    logger.warning("Memory session dispose failed: %s", e)

    def _should_execute_node(
        self,
        node: Node,
        incoming_edges: tuple[Edge, ...],
        completed: dict[NodeID, NodeResult],
        context: Context,  # Updated to Context
    ) -> bool:
        """Check if a node should be executed based on join semantics."""
        if not incoming_edges:
            return True

        join_mode = self._get_join_mode(node)
        satisfied_edges = [self._edge_satisfied(edge, completed, context) for edge in incoming_edges]

        if join_mode == "any":
            return any(satisfied_edges)

        return all(satisfied_edges)

    def _get_join_mode(self, node: Node) -> str:
        """Get join semantics for multi-incoming edges."""
        join_mode = ""
        if isinstance(node.config, dict):
            join_mode = str(node.config.get("join", node.config.get("join_mode", ""))).lower()

        if join_mode in {"any", "or"}:
            return "any"
        if join_mode in {"all", "and"}:
            return "all"
        return "all"

    def _edge_satisfied(
        self,
        edge: Edge,
        completed: dict[NodeID, NodeResult],
        context: Context,  # Updated to Context
    ) -> bool:
        """Check if an edge condition is satisfied."""
        source_result = completed.get(edge.source)
        if not source_result:
            return False

        allowed_targets = _current_route_choices().get(edge.source)
        if allowed_targets is not None and edge.target not in allowed_targets:
            return False

        if edge.condition == EdgeCondition.ALWAYS:
            return True
        if edge.condition == EdgeCondition.ON_SUCCESS:
            return source_result.success
        if edge.condition == EdgeCondition.ON_FAILURE:
            return not source_result.success
        if edge.condition == EdgeCondition.JSON_RULE:  # Removed CONDITIONAL
            if edge.condition_rule:
                try:
                    return edge.condition_rule.evaluate(context)
                except Exception as e:
                    # Log evaluation failure and return False as fallback
                    logger.warning(
                        "Edge condition evaluation failed: %s",
                        str(e),
                        edge_source=edge.source,
                        edge_target=edge.target,
                        exc_info=True,
                    )
                    return False
            return False

        return False

    def _apply_node_output(
        self,
        node: Node,
        result: NodeResult,
        context: Context,
    ) -> Context:
        """Update context with node output if configured."""
        if (result.success) and node.output_key and result.output is not None:
            # Create patch for provenance
            patch = ContextPatch(
                path=node.output_key,
                operation=PatchOperation.SET,
                value=result.output,
                source=self._get_patch_source(node),
                source_id=str(node.id),
                reason=f"Output from node '{node.id}'",
                correlation_id=_correlation_id_var.get(),
            )

            # Record patch
            if self._run_logger:
                self._run_logger.record_patch(patch)

            return context.apply(patch)
        return context

    def _get_patch_source(self, node: Node) -> PatchSource:
        """Get the appropriate patch source for a node type."""
        if node.type == NodeType.TOOL:
            return PatchSource.TOOL
        elif node.type == NodeType.AGENT:
            return PatchSource.AGENT
        elif node.type in (NodeType.ROUTER, NodeType.CONDITIONAL, NodeType.PARALLEL):
            return PatchSource.SYSTEM
        else:
            return PatchSource.SYSTEM

    # Node-type handlers delegated to cemaf.orchestration.node_handlers

    async def _execute_with_retry(
        self,
        node: Node,
        context: Context,  # Updated to Context
    ) -> tuple[NodeResult, Context]:  # Returns new Context
        """Execute a node with retry logic and autonomous healing."""
        # Handle max_retries=0 case - still try once
        max_attempts = max(1, node.max_retries) if node.retry_on_failure else 1
        last_error: str | None = None
        start_time = utc_now()
        current_context = context  # Keep track of context

        # Track heal attempts for this specific node execution run
        heal_attempts: set[str] = set()
        heal_count = 0  # Hard limit on healing attempts
        max_heal_attempts_per_node = 2  # Maximum healing attempts before giving up

        for attempt in range(max_attempts):
            try:
                # Resolve input_mapping dependencies before execution
                # This enables regex-based context chaining ($$STEP_N_OUTPUT$$)
                resolved_context = current_context
                if node.input_mapping:
                    # Resolve placeholders in input_mapping and create a context with resolved inputs
                    resolved_inputs = resolve_node_input(node.input_mapping, current_context)
                    # Store resolved inputs in context for the node executor to use
                    # Node executors can access these via context.get("_resolved_inputs")
                    resolved_context = current_context.set("_resolved_inputs", resolved_inputs)

                try:
                    result = await asyncio.wait_for(
                        self._node_executor.execute_node(node, resolved_context),
                        timeout=self._node_timeout,
                    )
                except TimeoutError:
                    result = NodeResult(
                        node_id=node.id,
                        success=False,
                        error=f"Node timed out after {self._node_timeout}s",
                    )

                # Enhance result metadata with token telemetry if available from agent results
                # NodeExecutors that execute agents should include agent metadata in NodeResult.metadata
                # This ensures token tracking flows through the execution pipeline

                # Apply output to context here, even if it's not a final success,
                # as intermediate results might be needed for subsequent retries
                # Use _apply_node_output to emit patches with correlation IDs
                current_context = self._apply_node_output(node, result, current_context)

                # Record cost to BudgetGuard on every execution that carries
                # telemetry, regardless of success. A failed-but-billed call
                # (e.g. LLM returned content-policy refusal after burning 10k
                # tokens) MUST still count against the cap — that's the exact
                # runaway-spend scenario a budget guard exists to catch.
                # We record unconditionally when metadata carries numbers,
                # NaN-safe so hostile agents can't corrupt accounting.
                if self._budget_guard is not None:
                    meta = result.metadata or {}
                    cost_raw = meta.get("cost_estimate_usd", meta.get("cost_usd", 0.0))
                    tokens_raw = meta.get("tokens_total", meta.get("tokens_used", 0))
                    try:
                        cost = float(cost_raw)
                        tokens = int(tokens_raw)
                    except (TypeError, ValueError):
                        cost, tokens = 0.0, 0
                    # NaN/inf guard — they're float values that pass isinstance
                    # but corrupt the accumulator.
                    import math

                    if math.isnan(cost) or math.isinf(cost):
                        cost = 0.0
                    if cost > 0 or tokens > 0:
                        self._budget_guard.record_usage(cost_usd=cost, tokens=tokens)

                if result.success:
                    return result, current_context

                last_error = result.error

                # Attempt Auto-Heal if manager is available
                if self._auto_heal_manager and not result.success:
                    from cemaf.core.result import Result

                    error_res: Result[None] = Result.fail(
                        result.error or "Node failed", metadata=result.metadata
                    )

                    # Check heal attempt limit (safeguard against infinite healing loops)
                    if heal_count >= max_heal_attempts_per_node:
                        logger.warning(
                            "Maximum healing attempts exceeded for node, giving up",
                            node_id=str(node.id),
                            max_heal_attempts=max_heal_attempts_per_node,
                            heal_count=heal_count,
                        )
                        # Stop retrying after healing has been exhausted without progress
                        # This prevents wasting resources on a problem healing can't solve
                        break
                    else:
                        # Track history before heal
                        history_before = current_context.get_timeline()
                        context_hash_before = current_context.state_hash()
                        heal_result = self._auto_heal_manager.heal(error_res, current_context)

                        if heal_result.success:
                            # Increment heal count ONCE healing is attempted (whether it helps or not)
                            heal_count += 1

                            # Prevent retrying same error state multiple times
                            state_hash = context_hash_before
                            heal_key = f"{state_hash}:{result.error}"

                            if heal_key in heal_attempts:
                                logger.warning(
                                    "Auto-heal already attempted for this state, giving up to prevent loop",
                                    node_id=str(node.id),
                                    state_hash=state_hash,
                                )
                                # If we give up on healing, we MUST NOT 'continue'.
                                # We let the loop proceed to the retry logic or exit.
                            elif heal_result.data is not None:
                                # Verify that healing actually changed the context state
                                context_hash_after = heal_result.data.state_hash()

                                if context_hash_after == context_hash_before:
                                    # Healing succeeded but didn't change context - likely won't help
                                    logger.warning(
                                        "Healing succeeded but didn't change context state, not retrying",
                                        node_id=str(node.id),
                                        state_hash=context_hash_before,
                                    )
                                else:
                                    # Healing succeeded AND changed context - proceed with retry
                                    heal_attempts.add(heal_key)
                                    logger.info(
                                        "Autonomous recovery successful for node",
                                        node_id=str(node.id),
                                        attempt=attempt + 1,
                                        heal_count=heal_count,
                                    )
                                    current_context = heal_result.data

                                    # Record any new patches created during healing
                                    if self._run_logger:
                                        history_after = current_context.get_timeline()
                                        new_patches = history_after[len(history_before) :]
                                        for patch in new_patches:
                                            self._run_logger.record_patch(patch)

                                    # We healed! We can now retry the node with the healed context.
                                    continue

                # Don't retry if retry_on_failure is False
                if not node.retry_on_failure:
                    break

            except Exception as e:
                last_error = str(e)

            # Don't sleep on last attempt
            if attempt < max_attempts - 1:
                await asyncio.sleep(0.1 * (attempt + 1))  # Exponential backoff

        end_time = utc_now()
        final_result = NodeResult(
            node_id=node.id,
            success=False,
            error=last_error or "Max retries exceeded",
            duration_ms=(end_time - start_time).total_seconds() * 1000,
        )
        return final_result, current_context

    async def run_parallel_nodes(
        self,
        nodes: tuple[Node, ...],
        context: Context,
    ) -> tuple[tuple[NodeResult, ...], Context]:
        """Execute multiple nodes in parallel with context merging."""
        handler_ctx = NodeHandlerContext(
            route_choices=_current_route_choices(),
            apply_output=self._apply_node_output,
            execute_with_retry=self._execute_with_retry,
            merge_strategy=self._merge_strategy,
            max_parallel=self._max_parallel,
            run_logger=self._run_logger,
            correlation_id=_correlation_id_var.get(),
        )
        return await _run_parallel_nodes(
            nodes=nodes,
            context=context,
            handler_ctx=handler_ctx,
        )
