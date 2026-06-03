"""Contract tests for cemaf.state.StateMachine — domain-neutral Order FSM."""

from __future__ import annotations

import asyncio

import pytest

from cemaf.state import (
    GuardRejected,
    HandlerFailed,
    HitlRequired,
    InMemoryFsmStore,
    StateMachine,
    Transition,
    TransitionNotAllowed,
    VersionConflict,
)
from tests.state.conftest import OrderEvent, OrderState, make_order_fsm


@pytest.mark.asyncio
async def test_happy_path_transitions_through_allowed_event(fsm) -> None:
    await fsm.create(fsm_id="ORD-1")

    state = await fsm.fire(
        fsm_id="ORD-1",
        event=OrderEvent.PAY,
        actor="cashier",
        actor_kind="human",
        correlation_id="run_abc123",
    )

    assert state.current_state == OrderState.PAID
    assert state.version == 1
    assert len(state.history) == 1
    assert state.history[0].from_state == OrderState.NEW
    assert state.history[0].to_state == OrderState.PAID
    assert state.history[0].event == OrderEvent.PAY
    assert state.history[0].correlation_id == "run_abc123"


@pytest.mark.asyncio
async def test_disallowed_transition_raises(fsm) -> None:
    await fsm.create(fsm_id="ORD-1")

    with pytest.raises(TransitionNotAllowed):
        await fsm.fire(
            fsm_id="ORD-1",
            event=OrderEvent.SHIP,
            actor="cashier",
            actor_kind="human",
            correlation_id="run_1",
        )

    state = await fsm.current(fsm_id="ORD-1")
    assert state.current_state == OrderState.NEW
    assert state.history == []


@pytest.mark.asyncio
async def test_hitl_blocks_agent_then_allows_human(fsm) -> None:
    await fsm.create(fsm_id="ORD-1")
    await fsm.fire(
        fsm_id="ORD-1",
        event=OrderEvent.PAY,
        actor="cashier",
        actor_kind="human",
        correlation_id="r1",
    )
    await fsm.fire(
        fsm_id="ORD-1",
        event=OrderEvent.SHIP,
        actor="warehouse-bot",
        actor_kind="agent",
        correlation_id="r2",
    )

    with pytest.raises(HitlRequired):
        await fsm.fire(
            fsm_id="ORD-1",
            event=OrderEvent.DELIVER,
            actor="delivery-bot",
            actor_kind="agent",
            correlation_id="r3",
        )
    state = await fsm.current(fsm_id="ORD-1")
    assert state.current_state == OrderState.SHIPPED

    state = await fsm.fire(
        fsm_id="ORD-1",
        event=OrderEvent.DELIVER,
        actor="driver",
        actor_kind="human",
        correlation_id="r4",
    )
    assert state.current_state == OrderState.DELIVERED


@pytest.mark.asyncio
async def test_guard_rejects_transition(fsm_with_guard) -> None:
    await fsm_with_guard.create(fsm_id="ORD-1")

    with pytest.raises(GuardRejected):
        await fsm_with_guard.fire(
            fsm_id="ORD-1",
            event=OrderEvent.PAY,
            actor="cashier",
            actor_kind="human",
            correlation_id="r1",
            payload={},
        )

    state = await fsm_with_guard.current(fsm_id="ORD-1")
    assert state.current_state == OrderState.NEW
    assert len(state.history) == 0


@pytest.mark.asyncio
async def test_guard_pass_with_payload(fsm_with_guard) -> None:
    await fsm_with_guard.create(fsm_id="ORD-1")

    state = await fsm_with_guard.fire(
        fsm_id="ORD-1",
        event=OrderEvent.PAY,
        actor="cashier",
        actor_kind="human",
        correlation_id="r1",
        payload={"payment_token": "tok_abc"},
    )

    assert state.current_state == OrderState.PAID


@pytest.mark.asyncio
async def test_handler_failure_rolls_back(fsm_with_failing_handler) -> None:
    await fsm_with_failing_handler.create(fsm_id="ORD-1")

    with pytest.raises(HandlerFailed):
        await fsm_with_failing_handler.fire(
            fsm_id="ORD-1",
            event=OrderEvent.PAY,
            actor="cashier",
            actor_kind="human",
            correlation_id="r1",
        )

    state = await fsm_with_failing_handler.current(fsm_id="ORD-1")
    assert state.current_state == OrderState.NEW
    assert len(state.history) == 0
    assert state.version == 0


@pytest.mark.asyncio
async def test_optimistic_locking_serializes_concurrent_fires() -> None:
    fsm_a = make_order_fsm(deliver_requires_hitl=False)
    await fsm_a.create(fsm_id="ORD-1")

    state = await fsm_a.current(fsm_id="ORD-1")
    store = InMemoryFsmStore()
    store._store[("order", "ORD-1")] = state  # noqa: SLF001

    new_a = state.model_copy(update={"current_state": OrderState.PAID, "version": 1})
    await store.save(state=new_a, expected_version=0)

    new_b = state.model_copy(update={"current_state": OrderState.PAID, "version": 1})
    with pytest.raises(VersionConflict):
        await store.save(state=new_b, expected_version=0)


@pytest.mark.asyncio
async def test_terminal_state_absorbs(fsm) -> None:
    await fsm.create(fsm_id="ORD-1")
    await fsm.fire(
        fsm_id="ORD-1",
        event=OrderEvent.CANCEL,
        actor="cashier",
        actor_kind="human",
        correlation_id="r1",
    )

    with pytest.raises(TransitionNotAllowed):
        await fsm.fire(
            fsm_id="ORD-1",
            event=OrderEvent.PAY,
            actor="cashier",
            actor_kind="human",
            correlation_id="r2",
        )


@pytest.mark.asyncio
async def test_correlation_id_required(fsm) -> None:
    await fsm.create(fsm_id="ORD-1")

    with pytest.raises(ValueError, match="correlation_id"):
        await fsm.fire(
            fsm_id="ORD-1",
            event=OrderEvent.PAY,
            actor="cashier",
            actor_kind="human",
            correlation_id="",
        )


@pytest.mark.asyncio
async def test_actor_required(fsm) -> None:
    await fsm.create(fsm_id="ORD-1")

    with pytest.raises(ValueError, match="actor"):
        await fsm.fire(
            fsm_id="ORD-1",
            event=OrderEvent.PAY,
            actor="",
            actor_kind="human",
            correlation_id="r1",
        )


@pytest.mark.asyncio
async def test_handler_dispatches_dag_inheriting_correlation_id(fsm) -> None:
    """Composition with DAGExecutor — handler payload carries correlation_id forward."""
    captured: dict[str, str] = {}

    async def dispatch_dag(state, payload) -> None:
        captured["correlation_id"] = state.history[-1].correlation_id
        captured["to_state"] = state.current_state

    transitions = [
        Transition(
            from_state=OrderState.NEW,
            event=OrderEvent.PAY,
            to_state=OrderState.PAID,
            handler=dispatch_dag,
        )
    ]
    fsm_with_dag = StateMachine[OrderState, OrderEvent](
        kind="order",
        states=OrderState,
        events=OrderEvent,
        transitions=transitions,
        store=InMemoryFsmStore(),
        initial_state=OrderState.NEW,
    )
    await fsm_with_dag.create(fsm_id="ORD-1")

    await fsm_with_dag.fire(
        fsm_id="ORD-1",
        event=OrderEvent.PAY,
        actor="cashier",
        actor_kind="human",
        correlation_id="run_inherit_test",
    )

    assert captured["correlation_id"] == "run_inherit_test"
    assert captured["to_state"] == OrderState.PAID


@pytest.mark.asyncio
async def test_history_is_append_only_and_carries_correlation(fsm) -> None:
    await fsm.create(fsm_id="ORD-1")

    await fsm.fire(
        fsm_id="ORD-1",
        event=OrderEvent.PAY,
        actor="cashier",
        actor_kind="human",
        correlation_id="r1",
    )
    await fsm.fire(
        fsm_id="ORD-1",
        event=OrderEvent.SHIP,
        actor="warehouse",
        actor_kind="human",
        correlation_id="r2",
    )

    history = await fsm.history(fsm_id="ORD-1")
    assert [t.correlation_id for t in history] == ["r1", "r2"]
    assert [t.event for t in history] == [OrderEvent.PAY, OrderEvent.SHIP]


@pytest.mark.asyncio
async def test_fsm_rejects_duplicate_transitions() -> None:
    duplicate = [
        Transition(from_state=OrderState.NEW, event=OrderEvent.PAY, to_state=OrderState.PAID),
        Transition(from_state=OrderState.NEW, event=OrderEvent.PAY, to_state=OrderState.CANCELLED),
    ]
    with pytest.raises(ValueError, match="duplicate transition"):
        StateMachine[OrderState, OrderEvent](
            kind="order",
            states=OrderState,
            events=OrderEvent,
            transitions=duplicate,
            store=InMemoryFsmStore(),
            initial_state=OrderState.NEW,
        )


@pytest.mark.asyncio
async def test_create_rejects_duplicate_fsm_id(fsm) -> None:
    await fsm.create(fsm_id="ORD-1")

    with pytest.raises(ValueError, match="already exists"):
        await fsm.create(fsm_id="ORD-1")


@pytest.mark.asyncio
async def test_graph_mermaid_renders(fsm) -> None:
    mermaid = fsm.graph_mermaid()

    assert mermaid.startswith("stateDiagram-v2")
    assert "new --> paid : pay" in mermaid
    assert "shipped --> delivered : deliver (HITL)" in mermaid
    assert "delivered --> [*]" in mermaid


@pytest.mark.asyncio
async def test_concurrent_fires_one_wins() -> None:
    fsm_x = make_order_fsm(deliver_requires_hitl=False)
    await fsm_x.create(fsm_id="ORD-race")

    async def attempt() -> bool:
        try:
            await fsm_x.fire(
                fsm_id="ORD-race",
                event=OrderEvent.PAY,
                actor="agent-a",
                actor_kind="agent",
                correlation_id=f"run_{id(asyncio.current_task())}",
            )
            return True
        except VersionConflict:
            return False
        except TransitionNotAllowed:
            return False

    results = await asyncio.gather(*[attempt() for _ in range(5)])
    assert sum(results) == 1, f"expected exactly one success, got {sum(results)} of 5"
