"""Node-type-specific execution handlers extracted from DAGExecutor."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cemaf.context.context import Context
from cemaf.context.merge import MergeConflictError, MergeStrategy
from cemaf.context.patch import ContextPatch, PatchOperation, PatchSource
from cemaf.core.types import NodeID
from cemaf.observability import get_logger
from cemaf.observability.run_logger import RunLogger
from cemaf.orchestration.dag import DAG, Node

logger = get_logger("orchestration.node_handlers")


@dataclass(frozen=True, slots=True)
class NodeHandlerContext:
    """Shared context for node type handlers.

    `should_halt` lets handlers (especially LOOP) opt into cooperative
    cancellation from outer-scope signals like QualityPolice. The outer
    executor only gets a chance to check halt state BETWEEN nodes, so
    LOOP's inner iterations must poll themselves — otherwise a degenerate
    loop wastes N-1 LLM calls after halt fires.
    """

    route_choices: dict[NodeID, set[NodeID]]
    apply_output: Callable[..., Context]
    execute_with_retry: Callable[..., Any]
    merge_strategy: MergeStrategy
    max_parallel: int
    run_logger: RunLogger | None
    correlation_id: str
    should_halt: Callable[[], bool] | None = None


def execute_router_node(
    node: Node,
    context: Context,
    *,
    handler_ctx: NodeHandlerContext,
) -> tuple[Any, Context]:
    """Execute a ROUTER node and select allowed downstream targets."""
    from cemaf.orchestration.executor import NodeResult

    route_fn = None
    route_key = "route"
    default_route = None

    if isinstance(node.config, dict):
        route_fn = node.config.get("route_fn")
        route_key = node.config.get("route_key", route_key)
        default_route = node.config.get("default_route")

    if callable(route_fn):
        selected = route_fn(context.data)
    else:
        selected = context.get(route_key)

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

    handler_ctx.route_choices[node.id] = set(targets)

    if targets:
        result = NodeResult(
            node_id=node.id,
            success=True,
            output=tuple(str(t) for t in targets),
        )
        new_context = handler_ctx.apply_output(node, result, context)
        return (result, new_context)

    result = NodeResult(
        node_id=node.id,
        success=False,
        error="No route selected",
        output=(),
    )
    new_context = handler_ctx.apply_output(node, result, context)
    return (result, new_context)


def execute_conditional_node(
    node: Node,
    context: Context,
    *,
    handler_ctx: NodeHandlerContext,
) -> tuple[Any, Context]:
    """Execute a CONDITIONAL node, evaluate condition, and set routing choices."""
    from cemaf.orchestration.executor import NodeResult

    condition_fn = None
    condition_key = "condition"
    condition_rule = None

    if isinstance(node.config, dict):
        condition_fn = node.config.get("condition_fn")
        condition_key = node.config.get("condition_key", condition_key)
        condition_rule = node.config.get("condition_rule")

    if callable(condition_fn):
        condition_value = bool(condition_fn(context.data))
    elif condition_rule:
        try:
            condition_value = bool(condition_rule.evaluate(context))
        except Exception as e:
            logger.warning(
                "Condition rule evaluation failed in node %s: %s",
                node.id,
                str(e),
                node_type=node.type.value,
                exc_info=True,
            )
            condition_value = False
    else:
        condition_value = bool(context.get(condition_key))

    # Determine allowed routes if provided on the node
    allowed_targets: set[NodeID] | None = None
    if node.routes:
        chosen = node.routes.get(condition_value, node.routes.get(str(condition_value), None))  # type: ignore[call-overload]
        allowed_targets = {NodeID(str(chosen))} if chosen is not None else set()
        handler_ctx.route_choices[node.id] = allowed_targets

    result = NodeResult(
        node_id=node.id,
        success=condition_value,
        output=condition_value,
        error=None if condition_value else "Condition evaluated to False",
    )
    new_context = handler_ctx.apply_output(node, result, context)
    return (result, new_context)


async def execute_loop_node(
    dag: DAG,
    node: Node,
    context: Context,
    *,
    handler_ctx: NodeHandlerContext,
) -> tuple[Any, list[Any], Context]:
    """Execute a LOOP node: iterate body nodes up to max_iterations."""
    from cemaf.orchestration.executor import NodeResult

    config = node.config or {}
    max_iterations: int = config.get("max_iterations", 10)
    exit_condition: str = config.get("exit_condition", "")
    body_node_ids: list[str] = config.get("body_node_ids", [])

    all_body_results: list[NodeResult] = []
    current_context = context

    if not body_node_ids:
        loop_result = NodeResult(
            node_id=node.id,
            success=True,
            output="completed 0 iterations (no body nodes)",
            metadata={"iterations_completed": 0},
        )
        return loop_result, all_body_results, current_context

    iteration = 0
    halted = False
    for iteration in range(max_iterations):
        # Cooperative halt — before each iteration check whether an outer
        # signal (QualityPolice, budget guard, cancellation) has been raised.
        # The outer executor only checks between nodes; without this poll, a
        # LOOP body burns N-1 iterations of real LLM calls after halt fires.
        if handler_ctx.should_halt is not None and handler_ctx.should_halt():
            halted = True
            logger.warning(
                "Loop halted by outer signal",
                loop_id=str(node.id),
                iteration=iteration,
            )
            break

        # Check exit condition (context key that evaluates truthy)
        if exit_condition and current_context.get(exit_condition, default=None):
            logger.info(
                "Loop exit condition met",
                loop_id=str(node.id),
                iteration=iteration,
                condition=exit_condition,
            )
            break

        # Execute each body node in sequence
        for body_id in body_node_ids:
            # Halt check between body nodes too — don't continue after the
            # first node in an iteration if halt fired mid-iteration.
            if handler_ctx.should_halt is not None and handler_ctx.should_halt():
                halted = True
                break

            body_node = dag.get_node(NodeID(body_id))
            if body_node is None:
                continue

            result, new_context = await handler_ctx.execute_with_retry(body_node, current_context)
            current_context = new_context
            all_body_results.append(result)

            if not result.success:
                loop_result = NodeResult(
                    node_id=node.id,
                    success=False,
                    error=f"Loop body node '{body_id}' failed at iteration {iteration}",
                    metadata={"iterations_completed": iteration},
                )
                return loop_result, all_body_results, current_context

        if halted:
            break

    if halted:
        loop_result = NodeResult(
            node_id=node.id,
            success=False,
            error=f"Loop halted by external signal after {iteration} iterations",
            metadata={"iterations_completed": iteration, "halted": True},
        )
    else:
        loop_result = NodeResult(
            node_id=node.id,
            success=True,
            output=f"completed {min(iteration + 1, max_iterations)} iterations",
            metadata={"iterations_completed": min(iteration + 1, max_iterations)},
        )
    return loop_result, all_body_results, current_context


async def execute_parallel_node(
    dag: DAG,
    node: Node,
    context: Context,
    *,
    handler_ctx: NodeHandlerContext,
) -> tuple[Any, tuple[Any, ...], Context]:
    """Execute a PARALLEL node's sub-nodes concurrently."""
    from cemaf.orchestration.executor import NodeResult

    if not node.parallel_nodes:
        return (
            NodeResult(
                node_id=node.id,
                success=False,
                error="Parallel node has no child nodes",
            ),
            (),
            context,
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
            context,
        )

    results, new_context = await run_parallel_nodes(
        nodes=tuple(sub_nodes),
        context=context,
        handler_ctx=handler_ctx,
    )

    failures = [r for r in results if not r.success]
    outputs: dict[str, Any] = {str(r.node_id): r.output for r in results if r.output is not None}

    error = None
    if failures:
        error = "; ".join(f"{r.node_id}: {r.error or 'failed'}" for r in failures)

    parallel_result = NodeResult(
        node_id=node.id,
        success=len(failures) == 0,
        output=outputs,
        error=error,
    )

    final_context = handler_ctx.apply_output(node, parallel_result, new_context)

    return (
        parallel_result,
        tuple(results),
        final_context,
    )


async def run_parallel_nodes(
    nodes: tuple[Node, ...],
    context: Context,
    *,
    handler_ctx: NodeHandlerContext,
) -> tuple[tuple[Any, ...], Context]:
    """Execute multiple nodes in parallel with context merging."""
    from cemaf.orchestration.executor import NodeResult

    semaphore = asyncio.Semaphore(handler_ctx.max_parallel)

    async def execute_with_semaphore(node: Node) -> tuple[NodeResult, Context]:
        async with semaphore:
            result, branch_context = await handler_ctx.execute_with_retry(node, context.copy_context())
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
            all_branch_contexts.append(context.copy_context())
        else:
            result, branch_context = res_tuple
            final_results.append(result)
            all_branch_contexts.append(branch_context)

    # Merge contexts from all parallel branches
    try:
        merge_result = handler_ctx.merge_strategy.merge(context, all_branch_contexts)

        if merge_result.conflicts and handler_ctx.run_logger:
            for conflict in merge_result.conflicts:
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
                    correlation_id=handler_ctx.correlation_id,
                )
                handler_ctx.run_logger.record_patch(conflict_patch)

        merged_context = merge_result.context

    except MergeConflictError as e:
        error_msg = f"Parallel merge failed: {e}"
        merged_context = context
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
