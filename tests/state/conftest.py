"""Shared fixtures — a domain-neutral OrderFsm exercising every spec scenario.

Domain choice: a generic Order workflow (NEW → PAID → SHIPPED → DELIVERED with
optional CANCEL). This is intentionally generic — cemaf.state must be domain-
agnostic. No iccha / engagement / agent vocabulary leaks into the framework
tests.
"""

from __future__ import annotations

from enum import StrEnum

import pytest

from cemaf.state import (
    InMemoryFsmStore,
    StateMachine,
    Transition,
)


class OrderState(StrEnum):
    NEW = "new"
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class OrderEvent(StrEnum):
    PAY = "pay"
    SHIP = "ship"
    DELIVER = "deliver"
    CANCEL = "cancel"


async def _has_payment_token(state, payload) -> bool:
    return payload.get("payment_token") is not None


async def _always_raise_handler(state, payload) -> None:
    raise RuntimeError("payment processor unreachable")


def make_order_fsm(
    *,
    pay_guard: bool = False,
    pay_handler_fails: bool = False,
    deliver_requires_hitl: bool = True,
) -> StateMachine[OrderState, OrderEvent]:
    """Builds a fresh FSM + store per test — no shared state."""
    transitions: list[Transition[OrderState, OrderEvent]] = [
        Transition(
            from_state=OrderState.NEW,
            event=OrderEvent.PAY,
            to_state=OrderState.PAID,
            guard=_has_payment_token if pay_guard else None,
            handler=_always_raise_handler if pay_handler_fails else None,
        ),
        Transition(
            from_state=OrderState.PAID,
            event=OrderEvent.SHIP,
            to_state=OrderState.SHIPPED,
        ),
        Transition(
            from_state=OrderState.SHIPPED,
            event=OrderEvent.DELIVER,
            to_state=OrderState.DELIVERED,
            requires_hitl=deliver_requires_hitl,
        ),
        Transition(
            from_state=OrderState.NEW,
            event=OrderEvent.CANCEL,
            to_state=OrderState.CANCELLED,
        ),
    ]
    return StateMachine[OrderState, OrderEvent](
        kind="order",
        states=OrderState,
        events=OrderEvent,
        transitions=transitions,
        store=InMemoryFsmStore(),
        initial_state=OrderState.NEW,
        terminal_states=frozenset({OrderState.DELIVERED, OrderState.CANCELLED}),
    )


@pytest.fixture
def fsm():
    return make_order_fsm()


@pytest.fixture
def fsm_with_guard():
    return make_order_fsm(pay_guard=True)


@pytest.fixture
def fsm_with_failing_handler():
    return make_order_fsm(pay_handler_fails=True)
