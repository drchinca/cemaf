"""Tests for state factory helpers."""

import pytest

from cemaf.state import FsmStore, InMemoryFsmStore, create_fsm_store, fsm_store_registry


def test_create_fsm_store_defaults_to_in_memory() -> None:
    store = create_fsm_store()

    assert isinstance(store, FsmStore)
    assert isinstance(store, InMemoryFsmStore)


def test_register_custom_fsm_store_backend() -> None:
    captured: dict[str, object] = {}

    class CustomFsmStore(InMemoryFsmStore):
        pass

    def factory(**kwargs: object) -> CustomFsmStore:
        captured.update(kwargs)
        return CustomFsmStore()

    fsm_store_registry.register(backend="unit-custom-fsm", factory=factory)

    store = create_fsm_store(backend="unit-custom-fsm", namespace="orders")

    assert isinstance(store, CustomFsmStore)
    assert captured["namespace"] == "orders"


def test_unknown_fsm_store_backend_names_registry() -> None:
    with pytest.raises(ValueError, match="fsm_store_registry.register"):
        create_fsm_store(backend="missing-fsm-store")
