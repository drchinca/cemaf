"""Factory helpers for state-machine persistence backends."""

from __future__ import annotations

from cemaf.state.persistence import FsmStore, InMemoryFsmStore


def create_fsm_store(*, backend: str = "memory") -> FsmStore:
    """Create an FSM persistence backend."""
    if backend == "memory":
        return InMemoryFsmStore()
    raise ValueError(f"Unsupported FSM store backend: {backend}")
