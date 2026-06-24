"""Tests for state factory helpers."""

from cemaf.state import FsmStore, InMemoryFsmStore, create_fsm_store


def test_create_fsm_store_defaults_to_in_memory() -> None:
    store = create_fsm_store()

    assert isinstance(store, FsmStore)
    assert isinstance(store, InMemoryFsmStore)
