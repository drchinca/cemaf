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
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from cemaf.context.context import Context
from cemaf.context.merge import (
    DEFAULT_MERGE_STRATEGY,
    MergeConflictError,
    MergeStrategy,
)
from cemaf.context.patch import ContextPatch, PatchOperation, PatchSource
from cemaf.core.constants import MAX_PARALLEL_NODES
from cemaf.core.enums import NodeType, RunStatus
from cemaf.core.execution import CancellationToken
from cemaf.core.recovery import AutoHealManager
from cemaf.core.types import JSON, NodeID, RunID
from cemaf.core.utils import utc_now
from cemaf.events.protocols import EventBus
from cemaf.moderation.pipeline import ModerationPipeline
from cemaf.observability import get_logger, get_metrics
from cemaf.observability.budget_guard import BudgetGuard
from cemaf.observability.health import HealthMonitor
from cemaf.observability.run_logger import RunLogger
from cemaf.orchestration.dag import DAG, Edge, EdgeCondition, Node
from cemaf.orchestration.dependency_resolver import resolve_node_input

logger = get_logger("orchestration.executor")
metrics = get_metrics()


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
    ) -> None:
        self._node_executor = node_executor
        self._max_parallel = max_parallel
        self._run_logger = run_logger
        self._event_bus = event_bus
        self._moderation_pipeline = moderation_pipeline
        self._merge_strategy = merge_strategy or DEFAULT_MERGE_STRATEGY
        self._route_choices: dict[NodeID, set[NodeID]] = {}
        self._correlation_id: str = ""
        self._health_registry = health_registry
        self._require_healthy = require_healthy
        self._auto_heal_manager = auto_heal_manager
        self._budget_guard = budget_guard

    async def run(
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
        run_id = run_id or RunID(f"run_{utc_now().isoformat()}")
        context = initial_context or Context()
        node_results: list[NodeResult] = []
        started_at = utc_now()
        self._route_choices = {}
        self._correlation_id = str(run_id)
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
                    ) = await self._execute_parallel_node(  # Added new_context
                        dag,
                        node,
                        context,
                    )
                    context = new_context  # Update context
                    node_results.append(group_result)
                    completed[node_id] = group_result

                    for parallel_result in parallel_results:
                        node_results.append(parallel_result)
                        completed[parallel_result.node_id] = parallel_result

                    result = group_result

                elif node.type == NodeType.ROUTER:
                    result, new_context = self._execute_router_node(node, context)  # Added new_context
                    context = new_context  # Update context
                    node_results.append(result)
                    completed[node_id] = result

                elif node.type == NodeType.CONDITIONAL:
                    result, new_context = self._execute_conditional_node(node, context)  # Added new_context
                    context = new_context  # Update context
                    node_results.append(result)
                    completed[node_id] = result

                elif node.type == NodeType.LOOP:
                    result, loop_results, new_context = await self._execute_loop_node(
                        dag,
                        node,
                        context,
                    )
                    context = new_context
                    node_results.append(result)
                    completed[node_id] = result
                    for loop_result in loop_results:
                        node_results.append(loop_result)
                    # Mark body nodes as completed so topo sort skips them
                    for body_id in (node.config or {}).get("body_node_ids", []):
                        completed[NodeID(body_id)] = result

                else:
                    # Standard execution (TOOL, SKILL, AGENT)
                    result, new_context = await self._execute_with_retry(node, context)  # Added new_context
                    context = new_context  # Update context
                    node_results.append(result)
                    completed[node_id] = result

                # Record per-node metrics
                node_type_name = node.type.value if hasattr(node.type, "value") else str(node.type)
                node_tags = {
                    "node_id": str(node_id),
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

                # Budget guard check after each node
                if self._budget_guard and result.success:
                    cost = result.metadata.get("cost_usd", 0.0) if result.metadata else 0.0
                    tokens = result.metadata.get("tokens_used", 0) if result.metadata else 0
                    self._budget_guard.record_usage(cost_usd=float(cost), tokens=int(tokens))
                    if self._budget_guard.should_halt():
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

                # Stop on failure if retry_on_failure is False
                if not result.success and not node.retry_on_failure and node.type != NodeType.CONDITIONAL:
                    # Record DAG failure metrics
                    completed_at = utc_now()
                    duration_ms = (completed_at - started_at).total_seconds() * 1000
                    error_type = type(result.error).__name__ if result.error else "Unknown"
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

        allowed_targets = self._route_choices.get(edge.source)
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
                correlation_id=self._correlation_id,
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

    def _execute_router_node(
        self, node: Node, context: Context
    ) -> tuple[NodeResult, Context]:  # Updated signature
        """Execute a ROUTER node and select allowed downstream targets."""
        route_fn = None
        route_key = "route"
        default_route = None

        if isinstance(node.config, dict):
            route_fn = node.config.get("route_fn")
            route_key = node.config.get("route_key", route_key)
            default_route = node.config.get("default_route")

        if callable(route_fn):
            selected = route_fn(context.data)  # Still uses context.data for callable
        else:
            selected = context.get(route_key)  # Updated to context.get

        if isinstance(selected, (list, tuple, set)):
            selections = list(selected)
        elif selected is None:
            selections = []
        else:
            selections = [selected]

        targets: list[NodeID] = []
        for selection in selections:
            target = node.routes.get(selection, selection)
            if target:
                targets.append(NodeID(str(target)))

        if not targets:
            fallback = default_route
            if fallback is None and "default" in node.routes:
                fallback = "default"
            if fallback is not None:
                fallback_target = node.routes.get(fallback, fallback)
                if fallback_target:
                    targets.append(NodeID(str(fallback_target)))

        self._route_choices[node.id] = set(targets)

        if targets:
            result = NodeResult(
                node_id=node.id,
                success=True,
                output=tuple(str(t) for t in targets),
            )
            new_context = self._apply_node_output(node, result, context)
            return (result, new_context)

        result = NodeResult(
            node_id=node.id,
            success=False,
            error="No route selected",
            output=(),
        )
        new_context = self._apply_node_output(node, result, context)
        return (result, new_context)

    def _execute_conditional_node(
        self, node: Node, context: Context
    ) -> tuple[NodeResult, Context]:  # Updated signature
        """Execute a CONDITIONAL node, evaluate condition, and set routing choices."""
        condition_fn = None
        condition_key = "condition"
        condition_rule = None

        if isinstance(node.config, dict):
            condition_fn = node.config.get("condition_fn")
            condition_key = node.config.get("condition_key", condition_key)
            condition_rule = node.config.get("condition_rule")

        if callable(condition_fn):
            condition_value = bool(condition_fn(context.data))  # Still uses context.data for callable
        elif condition_rule:
            try:
                condition_value = bool(condition_rule.evaluate(context))
            except Exception as e:
                # Log evaluation failure and default to False
                logger.warning(
                    "Condition rule evaluation failed in node %s: %s",
                    node.id,
                    str(e),
                    node_type=node.type.value,
                    exc_info=True,
                )
                condition_value = False
        else:
            condition_value = bool(context.get(condition_key))  # Updated to context.get

        # Determine allowed routes if provided on the node
        allowed_targets: set[NodeID] | None = None
        if node.routes:
            # Try boolean key first, then string key (supports both route types)
            # Type ignore: node.routes is JSON (dict[str, Any]) but we support bool keys too
            chosen = node.routes.get(condition_value, node.routes.get(str(condition_value), None))  # type: ignore[call-overload]
            allowed_targets = {NodeID(str(chosen))} if chosen is not None else set()
            self._route_choices[node.id] = allowed_targets

        result = NodeResult(
            node_id=node.id,
            success=condition_value,
            output=condition_value,
            error=None if condition_value else "Condition evaluated to False",
        )
        new_context = self._apply_node_output(node, result, context)
        return (result, new_context)

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

                result = await self._node_executor.execute_node(
                    node, resolved_context
                )  # Pass resolved context

                # Enhance result metadata with token telemetry if available from agent results
                # NodeExecutors that execute agents should include agent metadata in NodeResult.metadata
                # This ensures token tracking flows through the execution pipeline

                # Apply output to context here, even if it's not a final success,
                # as intermediate results might be needed for subsequent retries
                # Use _apply_node_output to emit patches with correlation IDs
                current_context = self._apply_node_output(node, result, current_context)

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

    async def _execute_loop_node(
        self,
        dag: DAG,
        loop_node: Node,
        context: Context,
    ) -> tuple[NodeResult, list[NodeResult], Context]:
        """Execute a LOOP node: iterate body nodes up to max_iterations."""
        config = loop_node.config or {}
        max_iterations: int = config.get("max_iterations", 10)
        exit_condition: str = config.get("exit_condition", "")
        body_node_ids: list[str] = config.get("body_node_ids", [])

        all_body_results: list[NodeResult] = []
        current_context = context

        for iteration in range(max_iterations):
            # Check exit condition (context key that evaluates truthy)
            if exit_condition and current_context.get(exit_condition, default=None):
                logger.info(
                    "Loop exit condition met",
                    loop_id=str(loop_node.id),
                    iteration=iteration,
                    condition=exit_condition,
                )
                break

            # Execute each body node in sequence
            for body_id in body_node_ids:
                body_node = dag.get_node(NodeID(body_id))
                if body_node is None:
                    continue

                result, new_context = await self._execute_with_retry(body_node, current_context)
                current_context = new_context
                all_body_results.append(result)

                if not result.success:
                    loop_result = NodeResult(
                        node_id=loop_node.id,
                        success=False,
                        error=f"Loop body node '{body_id}' failed at iteration {iteration}",
                        metadata={"iterations_completed": iteration},
                    )
                    return loop_result, all_body_results, current_context

        loop_result = NodeResult(
            node_id=loop_node.id,
            success=True,
            output=f"completed {min(iteration + 1, max_iterations)} iterations",
            metadata={"iterations_completed": min(iteration + 1, max_iterations)},
        )
        return loop_result, all_body_results, current_context

    async def _execute_parallel_node(
        self,
        dag: DAG,
        node: Node,
        context: Context,  # Updated to Context
    ) -> tuple[NodeResult, tuple[NodeResult, ...], Context]:  # Returns new Context
        """Execute a PARALLEL node's sub-nodes concurrently."""
        if not node.parallel_nodes:
            return (
                NodeResult(
                    node_id=node.id,
                    success=False,
                    error="Parallel node has no child nodes",
                ),
                (),
                context,  # Return original context
            )

        sub_nodes: list[Node] = []
        missing: list[str] = []
        for sub_id in node.parallel_nodes:
            sub_node = dag.get_node(sub_id)
            if sub_node:
                sub_nodes.append(sub_node)
            else:
                missing.append(str(sub_id))

        if missing:
            return (
                NodeResult(
                    node_id=node.id,
                    success=False,
                    error=f"Parallel node missing child nodes: {', '.join(missing)}",
                ),
                (),
                context,  # Return original context
            )

        results, new_context = await self.run_parallel_nodes(
            tuple(sub_nodes), context
        )  # Capture new_context from parallel execution

        failures = [r for r in results if not r.success]
        outputs: dict[str, Any] = {str(r.node_id): r.output for r in results if r.output is not None}

        error = None
        if failures:
            error = "; ".join(f"{r.node_id}: {r.error or 'failed'}" for r in failures)

        # Create result for the parallel node itself
        parallel_result = NodeResult(
            node_id=node.id,
            success=len(failures) == 0,
            output=outputs,
            error=error,
        )

        # Apply parallel node's own output_key if set, using _apply_node_output to emit patches
        final_context = self._apply_node_output(node, parallel_result, new_context)

        return (
            parallel_result,
            tuple(results),
            final_context,  # Return final context
        )

    async def run_parallel_nodes(
        self,
        nodes: tuple[Node, ...],
        context: Context,  # Updated to Context
    ) -> tuple[tuple[NodeResult, ...], Context]:  # Returns new Context
        """
        Execute multiple nodes in parallel (standalone utility).

        Uses the configured merge strategy to combine branch contexts.
        The merge strategy determines how conflicts are handled when
        multiple branches write to the same context keys.
        """
        semaphore = asyncio.Semaphore(self._max_parallel)

        # Each parallel execution will get a *copy* of the current context
        # and return its modified context. These will then be merged.

        async def execute_with_semaphore(node: Node) -> tuple[NodeResult, Context]:
            async with semaphore:
                # Pass a clone of the context to each parallel branch to ensure isolation
                result, branch_context = await self._execute_with_retry(node, context.copy_context())
                # For parallel nodes, we should apply output of each child node to its branch_context
                # This is already handled inside _execute_with_retry for TOOL/SKILL/AGENT
                # so we just return the result and the branch_context
                return result, branch_context

        tasks = [execute_with_semaphore(node) for node in nodes]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        final_results: list[NodeResult] = []
        all_branch_contexts: list[Context] = []

        for i, res_tuple in enumerate(raw_results):
            if isinstance(res_tuple, BaseException):
                final_results.append(
                    NodeResult(
                        node_id=nodes[i].id,
                        success=False,
                        error=str(res_tuple),
                    )
                )
                all_branch_contexts.append(context.copy_context())  # Failed branch, no changes
            else:
                result, branch_context = res_tuple
                final_results.append(result)
                all_branch_contexts.append(branch_context)

        # Merge contexts from all parallel branches using configured strategy
        try:
            merge_result = self._merge_strategy.merge(context, all_branch_contexts)

            # Log conflicts for observability (even when merge succeeds)
            if merge_result.conflicts and self._run_logger:
                for conflict in merge_result.conflicts:
                    # Record conflict as a system patch for debugging
                    conflict_patch = ContextPatch(
                        path=f"_merge_conflicts.{conflict.key}",
                        operation=PatchOperation.SET,
                        value={
                            "key": conflict.key,
                            "values": [str(v) for v in conflict.values],
                            "branches": conflict.branch_indices,
                            "resolution": "last_write_wins",
                        },
                        source=PatchSource.SYSTEM,
                        source_id="parallel_merge",
                        reason=f"Merge conflict detected for key '{conflict.key}'",
                        correlation_id=self._correlation_id,
                    )
                    self._run_logger.record_patch(conflict_patch)

            merged_context = merge_result.context

        except MergeConflictError as e:
            # Strategy raised on conflict - propagate error
            # Create a partial result with the error
            error_msg = f"Parallel merge failed: {e}"
            # Return base context on merge failure
            merged_context = context
            # Update all results to reflect merge failure
            final_results = [
                NodeResult(
                    node_id=r.node_id,
                    success=False,
                    output=r.output,
                    error=error_msg if not r.error else f"{r.error}; {error_msg}",
                    duration_ms=r.duration_ms,
                    metadata={**r.metadata, "_merge_conflict": True},
                )
                for r in final_results
            ]

        return tuple(final_results), merged_context
