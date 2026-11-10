"""Tests for extracted node-type handlers."""

import pytest

from cemaf.collision import (
    Advisory,
    AdvisoryLevel,
    AgentWriteSet,
    CollisionChannels,
    CollisionPolicy,
    create_collision_policy,
)
from cemaf.context.context import Context
from cemaf.context.merge import DEFAULT_MERGE_STRATEGY, MergeStrategy, ReducerMergeStrategy
from cemaf.core.enums import NodeType
from cemaf.core.types import NodeID
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.executor import NodeResult
from cemaf.orchestration.node_handlers import (
    NodeHandlerContext,
    ParallelWritePlan,
    execute_conditional_node,
    execute_loop_node,
    execute_router_node,
    plan_parallel_writes,
)


def _noop_apply_output(node: Node, result: NodeResult, context: Context) -> Context:
    """Pass-through apply_output for testing."""
    return context


async def _success_execute(node: Node, context: Context) -> tuple[NodeResult, Context]:
    """Mock execute_with_retry that always succeeds."""
    result = NodeResult(
        node_id=node.id,
        success=True,
        output=f"output_{node.id}",
    )
    return result, context


async def _failing_execute(node: Node, context: Context) -> tuple[NodeResult, Context]:
    """Mock execute_with_retry that always fails."""
    result = NodeResult(
        node_id=node.id,
        success=False,
        error=f"Node '{node.id}' failed",
    )
    return result, context


def _make_handler_ctx(
    *,
    route_choices: dict[NodeID, set[NodeID]] | None = None,
    execute_fn: object | None = None,
) -> NodeHandlerContext:
    """Build a minimal NodeHandlerContext for testing."""
    return NodeHandlerContext(
        route_choices=route_choices if route_choices is not None else {},
        apply_output=_noop_apply_output,
        execute_with_retry=execute_fn or _success_execute,
        merge_strategy=DEFAULT_MERGE_STRATEGY,
        max_parallel=4,
        run_logger=None,
        correlation_id="test-run",
    )


# ---------- Router node tests ----------


class TestExecuteRouterNode:
    def test_route_fn_selects_target(self) -> None:
        """Router node with route_fn callable picks the right target."""
        node = Node(
            id=NodeID("router1"),
            type=NodeType.ROUTER,
            name="Router",
            routes={"a": "node_a", "b": "node_b"},
            config={"route_fn": lambda data: "a"},
        )
        handler_ctx = _make_handler_ctx()
        context = Context()

        result, _ = execute_router_node(node, context, handler_ctx=handler_ctx)

        assert result.success is True
        assert "node_a" in result.output
        assert handler_ctx.route_choices[node.id] == {NodeID("node_a")}

    def test_route_key_from_context(self) -> None:
        """Router node reads route selection from context key."""
        node = Node(
            id=NodeID("router2"),
            type=NodeType.ROUTER,
            name="Router",
            routes={"x": "node_x", "y": "node_y"},
            config={"route_key": "chosen_route"},
        )
        handler_ctx = _make_handler_ctx()
        context = Context(data={"chosen_route": "y"})

        result, _ = execute_router_node(node, context, handler_ctx=handler_ctx)

        assert result.success is True
        assert "node_y" in result.output

    def test_default_route_when_no_match(self) -> None:
        """Router falls back to default route when no selection matches."""
        node = Node(
            id=NodeID("router3"),
            type=NodeType.ROUTER,
            name="Router",
            routes={"a": "node_a", "default": "node_default"},
            config={"route_key": "missing_key"},
        )
        handler_ctx = _make_handler_ctx()
        context = Context()

        result, _ = execute_router_node(node, context, handler_ctx=handler_ctx)

        assert result.success is True
        assert "node_default" in result.output

    def test_no_route_fails(self) -> None:
        """Router with no matching route and no default fails."""
        node = Node(
            id=NodeID("router4"),
            type=NodeType.ROUTER,
            name="Router",
            routes={"a": "node_a"},
            config={"route_key": "missing_key"},
        )
        handler_ctx = _make_handler_ctx()
        context = Context()

        result, _ = execute_router_node(node, context, handler_ctx=handler_ctx)

        assert result.success is False
        assert result.error == "No route selected"


# ---------- Conditional node tests ----------


class TestExecuteConditionalNode:
    def test_condition_true(self) -> None:
        """Conditional node evaluates truthy condition from context."""
        node = Node.conditional(
            id="cond1",
            name="Conditional",
            condition="is_ready",
        )
        handler_ctx = _make_handler_ctx()
        context = Context(data={"is_ready": True})

        result, _ = execute_conditional_node(node, context, handler_ctx=handler_ctx)

        assert result.success is True
        assert result.output is True
        assert result.error is None

    def test_condition_false(self) -> None:
        """Conditional node evaluates falsy condition from context."""
        node = Node.conditional(
            id="cond2",
            name="Conditional",
            condition="is_ready",
        )
        handler_ctx = _make_handler_ctx()
        context = Context(data={"is_ready": False})

        result, _ = execute_conditional_node(node, context, handler_ctx=handler_ctx)

        assert result.success is False
        assert result.output is False
        assert result.error == "Condition evaluated to False"

    def test_condition_fn_callable(self) -> None:
        """Conditional node uses a callable condition_fn."""
        node = Node.conditional(
            id="cond3",
            name="Conditional",
            condition=lambda data: data.get("score", 0) > 5,
        )
        handler_ctx = _make_handler_ctx()
        context = Context(data={"score": 10})

        result, _ = execute_conditional_node(node, context, handler_ctx=handler_ctx)

        assert result.success is True

    def test_condition_with_routes(self) -> None:
        """Conditional node sets route_choices when routes are configured."""
        node = Node.conditional(
            id="cond4",
            name="Conditional",
            condition="flag",
            routes={True: "true_node", False: "false_node"},
        )
        handler_ctx = _make_handler_ctx()
        context = Context(data={"flag": True})

        result, _ = execute_conditional_node(node, context, handler_ctx=handler_ctx)

        assert result.success is True
        assert handler_ctx.route_choices[node.id] == {NodeID("true_node")}


# ---------- Loop node tests ----------


class TestExecuteLoopNode:
    @pytest.mark.asyncio
    async def test_loop_with_exit_condition(self) -> None:
        """Loop exits early when exit condition key becomes truthy."""
        iteration_count = 0

        async def counting_execute(node: Node, context: Context) -> tuple[NodeResult, Context]:
            nonlocal iteration_count
            iteration_count += 1
            # Set exit condition after 2 iterations
            if iteration_count >= 2:
                context = context.set("done", True)
            result = NodeResult(node_id=node.id, success=True, output=f"iter_{iteration_count}")
            return result, context

        body_node = Node(
            id=NodeID("body1"),
            type=NodeType.TOOL,
            name="Body",
            ref_id="tool_body",
        )
        loop_node = Node(
            id=NodeID("loop1"),
            type=NodeType.LOOP,
            name="Loop",
            config={
                "max_iterations": 10,
                "exit_condition": "done",
                "body_node_ids": ["body1"],
            },
        )
        dag = DAG(name="test_loop")
        dag = dag.add_node(body_node)
        dag = dag.add_node(loop_node)

        handler_ctx = _make_handler_ctx(execute_fn=counting_execute)
        context = Context()

        result, body_results, _ = await execute_loop_node(dag, loop_node, context, handler_ctx=handler_ctx)

        assert result.success is True
        assert iteration_count == 2
        assert len(body_results) == 2

    @pytest.mark.asyncio
    async def test_loop_max_iterations(self) -> None:
        """Loop stops after max_iterations even without exit condition."""
        body_node = Node(
            id=NodeID("body1"),
            type=NodeType.TOOL,
            name="Body",
            ref_id="tool_body",
        )
        loop_node = Node(
            id=NodeID("loop1"),
            type=NodeType.LOOP,
            name="Loop",
            config={
                "max_iterations": 3,
                "body_node_ids": ["body1"],
            },
        )
        dag = DAG(name="test_loop")
        dag = dag.add_node(body_node)
        dag = dag.add_node(loop_node)

        handler_ctx = _make_handler_ctx()
        context = Context()

        result, body_results, _ = await execute_loop_node(dag, loop_node, context, handler_ctx=handler_ctx)

        assert result.success is True
        assert len(body_results) == 3
        assert result.metadata["iterations_completed"] == 3

    @pytest.mark.asyncio
    async def test_loop_body_failure_stops_loop(self) -> None:
        """Loop stops when a body node fails."""
        body_node = Node(
            id=NodeID("body1"),
            type=NodeType.TOOL,
            name="Body",
            ref_id="tool_body",
        )
        loop_node = Node(
            id=NodeID("loop1"),
            type=NodeType.LOOP,
            name="Loop",
            config={
                "max_iterations": 5,
                "body_node_ids": ["body1"],
            },
        )
        dag = DAG(name="test_loop")
        dag = dag.add_node(body_node)
        dag = dag.add_node(loop_node)

        handler_ctx = _make_handler_ctx(execute_fn=_failing_execute)
        context = Context()

        result, body_results, _ = await execute_loop_node(dag, loop_node, context, handler_ctx=handler_ctx)

        assert result.success is False
        assert "failed at iteration 0" in result.error
        assert len(body_results) == 1


def _writer(*, node_id: str, output_key: str) -> Node:
    """An agent node that writes one context key."""
    return Node.agent(id=node_id, name=node_id, agent_id=node_id, output_key=output_key)


class SteerEarlierPolicy:
    """Custom policy that always steers the first write set it is given."""

    def advise(self, a: AgentWriteSet, b: AgentWriteSet) -> Advisory:
        return Advisory(
            level=AdvisoryLevel.RESOLUTION_ADVISORY,
            risk=1.0,
            channels=CollisionChannels(overlap=1.0, dependency=0.0, tree=0.0),
            transmit=True,
            steer=a.agent_id,
            hold=b.agent_id,
        )


def _plan(
    *nodes: Node,
    policy: CollisionPolicy | None = None,
    merge_strategy: MergeStrategy = DEFAULT_MERGE_STRATEGY,
) -> ParallelWritePlan:
    """Plan with the default policy and last-write-wins unless told otherwise."""
    return plan_parallel_writes(
        nodes=nodes,
        policy=policy or create_collision_policy(),
        merge_strategy=merge_strategy,
    )


class TestPlanParallelWrites:
    """Sibling-order resolution of overlapping PARALLEL writes (SPEC-12 §2.4)."""

    def test_same_key_steers_the_later_sibling(self) -> None:
        plan = _plan(
            _writer(node_id="first", output_key="decision"), _writer(node_id="second", output_key="decision")
        )

        assert [(s.node_id, s.held_by, s.output_key) for s in plan.steered] == [
            (NodeID("second"), NodeID("first"), "decision")
        ]
        assert [a.node_id for a in plan.advisories] == [NodeID("second")]

    def test_paths_sharing_a_top_level_key_collide(self) -> None:
        plan = _plan(
            _writer(node_id="left", output_key="results.a"), _writer(node_id="right", output_key="results.b")
        )

        assert [s.node_id for s in plan.steered] == [NodeID("right")]

    def test_different_top_level_keys_steer_nobody_and_publish_nothing(self) -> None:
        plan = _plan(
            _writer(node_id="research", output_key="research"),
            _writer(node_id="outline", output_key="outline"),
        )

        assert plan.steered == ()
        assert plan.advisories == ()

    def test_children_without_an_output_key_are_ignored(self) -> None:
        plan = _plan(_writer(node_id="first", output_key=""), _writer(node_id="second", output_key=""))

        assert plan.steered == ()

    def test_keys_the_merge_strategy_handles_are_left_alone(self) -> None:
        plan = _plan(
            _writer(node_id="first", output_key="findings"),
            _writer(node_id="second", output_key="findings"),
            merge_strategy=ReducerMergeStrategy(reducers={"findings": list}),
        )

        assert plan.steered == ()

    def test_policy_may_steer_the_earlier_sibling_who_then_steers_nobody(self) -> None:
        plan = _plan(
            _writer(node_id="a", output_key="decision"),
            _writer(node_id="b", output_key="decision"),
            _writer(node_id="c", output_key="decision"),
            policy=SteerEarlierPolicy(),
        )

        # a vs b steers a; a is then out, so b vs c is judged next and steers b. c runs.
        assert [(s.node_id, s.held_by) for s in plan.steered] == [
            (NodeID("a"), NodeID("b")),
            (NodeID("b"), NodeID("c")),
        ]
