"""Integration: StateMachine + SqliteFsmStore — FSM state survives a restart.

Wires the real FSM engine to the real SQLite store (no fakes): create → fire →
close the store → reopen a fresh store + fresh StateMachine on the same db path
→ history and current state are intact and the machine keeps firing from where
it left off.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import pytest

from cemaf.state import SqliteFsmStore, StateMachine, Transition, VersionConflict


class OrderState(StrEnum):
    NEW = "new"
    PAID = "paid"
    SHIPPED = "shipped"


class OrderEvent(StrEnum):
    PAY = "pay"
    SHIP = "ship"


def _build_fsm(store: SqliteFsmStore) -> StateMachine[OrderState, OrderEvent]:
    return StateMachine[OrderState, OrderEvent](
        kind="order",
        states=OrderState,
        events=OrderEvent,
        transitions=[
            Transition(from_state=OrderState.NEW, event=OrderEvent.PAY, to_state=OrderState.PAID),
            Transition(from_state=OrderState.PAID, event=OrderEvent.SHIP, to_state=OrderState.SHIPPED),
        ],
        store=store,
        initial_state=OrderState.NEW,
        terminal_states=frozenset({OrderState.SHIPPED}),
    )


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "fsm_integration.db")


async def test_fsm_survives_restart_and_continues(db_path: str) -> None:
    """Fire through one store instance, resume through another."""
    async with SqliteFsmStore(db_path=db_path) as store:
        fsm = _build_fsm(store)
        await fsm.create(fsm_id="ORD-9", metadata={"tenant": "t1"})
        state = await fsm.fire(
            fsm_id="ORD-9",
            event=OrderEvent.PAY,
            actor="cashier",
            actor_kind="human",
            correlation_id="run_1",
            payload={"payment_token": "tok"},
        )
        assert state.current_state == OrderState.PAID
        assert state.version == 1

    # "Restart": fresh store connection + fresh machine over the same file.
    async with SqliteFsmStore(db_path=db_path) as store:
        fsm = _build_fsm(store)

        current = await fsm.current(fsm_id="ORD-9")
        assert current.current_state == OrderState.PAID
        assert current.metadata == {"tenant": "t1"}

        history = await fsm.history(fsm_id="ORD-9")
        assert [t.event for t in history] == ["pay"]
        assert history[0].correlation_id == "run_1"

        state = await fsm.fire(
            fsm_id="ORD-9",
            event=OrderEvent.SHIP,
            actor="warehouse",
            actor_kind="human",
            correlation_id="run_2",
        )
        assert state.current_state == OrderState.SHIPPED
        assert state.version == 2
        assert [t.event for t in state.history] == ["pay", "ship"]


async def test_two_machines_same_db_optimistic_lock(db_path: str) -> None:
    """Two machines over the same record: the stale one hits VersionConflict."""
    async with SqliteFsmStore(db_path=db_path) as store_a, SqliteFsmStore(db_path=db_path) as store_b:
        fsm_a = _build_fsm(store_a)
        fsm_b = _build_fsm(store_b)
        await fsm_a.create(fsm_id="ORD-10")

        # B loads the NEW record, then A advances it underneath.
        stale = await fsm_b.current(fsm_id="ORD-10")
        assert stale.version == 0
        await fsm_a.fire(
            fsm_id="ORD-10",
            event=OrderEvent.PAY,
            actor="cashier",
            actor_kind="human",
            correlation_id="run_a",
        )

        # B's save against the stale version must be rejected by the store.
        with pytest.raises(VersionConflict):
            await store_b.save(state=stale.model_copy(update={"version": 1}), expected_version=0)
