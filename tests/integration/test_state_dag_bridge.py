"""Integration test: cemaf.state.StateMachine → cemaf.orchestration.DAGExecutor.

Proves the composition claim from the state primitive's docstring is real, not a
dead-end seam (per the house rule in CLAUDE.md: a bridge without a test that
feeds its output into the target system is not an integration).

The seam under test: a `Transition.handler` dispatches a real `DAGExecutor.run()`.
We assert (a) firing the transition actually executes the DAG with a real
executor, (b) the FSM lands in the target state only when the DAG succeeds, and
(c) the firing `correlation_id` is observable inside the handler so telemetry can
join FSM transitions to DAG runs.
"""

from __future__ import annotations

from enum import StrEnum

import pytest

from cemaf.context.context import Context
from cemaf.core.types import NodeID
from cemaf.orchestration.dag import DAG, Edge, Node
from cemaf.orchestration.executor import DAGExecutor
from cemaf.state import (
    FsmState,
    HandlerFailed,
    InMemoryFsmStore,
    StateMachine,
    Transition,
)
from tests.conftest import MockNodeExecutor


class OrderState(StrEnum):
    NEW = "new"
    FULFILLING = "fulfilling"
    FULFILLED = "fulfilling_done"
    FAILED = "failed"


class OrderEvent(StrEnum):
    FULFILL = "fulfill"


def _build_simple_dag() -> DAG:
    """Canonical linear A→B→C DAG (mirrors the conftest simple_dag fixture)."""
    dag = DAG(name="fulfillment-dag", description="state→DAG bridge test")
    dag = dag.add_node(Node.tool(id="a", name="Step A", tool_id="tool_a", output_key="a_out"))
    dag = dag.add_node(Node.tool(id="b", name="Step B", tool_id="tool_b", output_key="b_out"))
    dag = dag.add_node(Node.tool(id="c", name="Step C", tool_id="tool_c", output_key="c_out"))
    dag = dag.add_edge(Edge(source=NodeID("a"), target=NodeID("b")))
    dag = dag.add_edge(Edge(source=NodeID("b"), target=NodeID("c")))
    return dag


@pytest.mark.asyncio
async def test_transition_handler_dispatches_real_dag() -> None:
    """fire(FULFILL) runs a real DAGExecutor; FSM lands in FULFILLED; correlation flows."""
    executor_calls: list[str] = []
    seen_correlation: dict[str, str] = {}
    node_executor = MockNodeExecutor()
    executor = DAGExecutor(node_executor=node_executor)
    dag = _build_simple_dag()

    async def on_fulfill(state: FsmState, payload: dict[str, object]) -> None:
        # The handler is the bridge: it dispatches a REAL DAG run.
        seen_correlation["cid"] = state.history[-1].correlation_id
        result = await executor.run(dag, initial_context=Context(data={"order": state.fsm_id}))
        if not result.success:
            raise RuntimeError("dag failed")
        executor_calls.append(state.fsm_id)

    fsm = StateMachine[OrderState, OrderEvent](
        kind="order",
        states=OrderState,
        events=OrderEvent,
        transitions=[
            Transition(
                from_state=OrderState.NEW,
                event=OrderEvent.FULFILL,
                to_state=OrderState.FULFILLED,
                handler=on_fulfill,
            )
        ],
        store=InMemoryFsmStore(),
        initial_state=OrderState.NEW,
        terminal_states=frozenset({OrderState.FULFILLED, OrderState.FAILED}),
    )

    await fsm.create(fsm_id="ORD-1")
    final = await fsm.fire(
        fsm_id="ORD-1",
        event=OrderEvent.FULFILL,
        actor="fulfillment-agent",
        actor_kind="agent",
        correlation_id="run_xyz",
    )

    # (a) the real DAG actually ran all three nodes
    assert node_executor.executed == ["a", "b", "c"]
    assert executor_calls == ["ORD-1"]
    # (b) FSM advanced to the target state after the DAG succeeded
    assert final.current_state == OrderState.FULFILLED
    # (c) the firing correlation_id was observable inside the handler (telemetry join key)
    assert seen_correlation["cid"] == "run_xyz"


@pytest.mark.asyncio
async def test_dag_failure_rolls_back_fsm_state() -> None:
    """If the dispatched DAG fails, the handler raises and the FSM does NOT advance."""
    from cemaf.orchestration.executor import NodeResult

    node_executor = MockNodeExecutor(
        node_results={"c": NodeResult(node_id=NodeID("c"), success=False, error="Intentional failure")}
    )
    executor = DAGExecutor(node_executor=node_executor)
    dag = _build_simple_dag()

    async def on_fulfill(state: FsmState, payload: dict[str, object]) -> None:
        result = await executor.run(dag, initial_context=Context(data={}))
        # Inspect node-level results directly — the handler's contract is "all nodes
        # succeeded", which is stricter than DAGExecutor.run's overall success flag
        # (the executor can report success while a leaf node failed if it was reachable
        # only via ON_SUCCESS edges). This is the realistic shape of a fulfillment
        # handler: any failed node means the order is not fulfilled.
        all_ok = result.success and all(nr.success for nr in result.node_results.values())
        if not all_ok:
            raise RuntimeError("dag had a failed node")

    fsm = StateMachine[OrderState, OrderEvent](
        kind="order",
        states=OrderState,
        events=OrderEvent,
        transitions=[
            Transition(
                from_state=OrderState.NEW,
                event=OrderEvent.FULFILL,
                to_state=OrderState.FULFILLED,
                handler=on_fulfill,
            )
        ],
        store=InMemoryFsmStore(),
        initial_state=OrderState.NEW,
    )

    await fsm.create(fsm_id="ORD-2")
    with pytest.raises(HandlerFailed):
        await fsm.fire(
            fsm_id="ORD-2",
            event=OrderEvent.FULFILL,
            actor="fulfillment-agent",
            actor_kind="agent",
            correlation_id="run_fail",
        )

    # Handler-failure rollback: state unchanged, history empty (per state §3 invariant 6)
    current = await fsm.current(fsm_id="ORD-2")
    assert current.current_state == OrderState.NEW
    assert current.history == []
    assert current.version == 0
