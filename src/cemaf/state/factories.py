"""Factory helpers for state-machine persistence backends."""

from __future__ import annotations

from typing import Any

from cemaf.core.provider_registry import ProviderRegistry
from cemaf.state.persistence import FsmStore, InMemoryFsmStore

fsm_store_registry: ProviderRegistry[FsmStore] = ProviderRegistry(name="fsm_store")


def _create_memory_fsm_store(**kwargs: Any) -> FsmStore:
    return InMemoryFsmStore()


fsm_store_registry.register(backend="memory", factory=_create_memory_fsm_store)


def create_fsm_store(*, backend: str = "memory", **backend_options: Any) -> FsmStore:
    """Create an FSM persistence backend."""
    return fsm_store_registry.create(backend=backend, **backend_options)
