"""Tests for memory factory functions."""

import pytest

from cemaf.events.bus import InMemoryEventBus
from cemaf.memory.base import InMemoryStore
from cemaf.memory.factories import (
    create_memory_manager,
    create_memory_store,
    create_memory_store_from_config,
    create_session_manager,
)
from cemaf.memory.manager import DefaultMemoryManager
from cemaf.memory.session import DefaultSessionManager

# ---------------------------------------------------------------------------
# create_memory_store
# ---------------------------------------------------------------------------


class TestCreateMemoryStore:
    def test_valid_backend_returns_in_memory_store(self) -> None:
        store = create_memory_store(backend="memory")
        assert isinstance(store, InMemoryStore)

    def test_default_backend_returns_in_memory_store(self) -> None:
        store = create_memory_store()
        assert isinstance(store, InMemoryStore)

    def test_invalid_backend_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="MemoryBackend"):
            create_memory_store(backend="redis")

    def test_custom_parameters_accepted(self) -> None:
        store = create_memory_store(
            backend="memory",
            max_items=5000,
            default_ttl_seconds=7200.0,
        )
        assert isinstance(store, InMemoryStore)


# ---------------------------------------------------------------------------
# create_memory_store_from_config
# ---------------------------------------------------------------------------


class TestCreateMemoryStoreFromConfig:
    def test_default_env_vars_return_in_memory_store(self) -> None:
        store = create_memory_store_from_config()
        assert isinstance(store, InMemoryStore)

    def test_custom_env_vars_return_in_memory_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CEMAF_MEMORY_BACKEND", "memory")
        monkeypatch.setenv("CEMAF_MEMORY_MAX_ITEMS", "500")
        monkeypatch.setenv("CEMAF_MEMORY_DEFAULT_TTL_SECONDS", "1800.0")

        store = create_memory_store_from_config()
        assert isinstance(store, InMemoryStore)

    def test_unsupported_backend_raises_value_error_with_helpful_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CEMAF_MEMORY_BACKEND", "cassandra")

        with pytest.raises(ValueError, match="Unsupported memory backend: cassandra"):
            create_memory_store_from_config()

    def test_error_message_mentions_extension_point(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CEMAF_MEMORY_BACKEND", "dynamodb")

        with pytest.raises(ValueError, match="extend create_memory_store_from_config"):
            create_memory_store_from_config()


# ---------------------------------------------------------------------------
# create_memory_manager
# ---------------------------------------------------------------------------


class TestCreateMemoryManager:
    def test_returns_default_memory_manager(self) -> None:
        manager = create_memory_manager()
        assert isinstance(manager, DefaultMemoryManager)

    def test_accepts_custom_memory_store(self) -> None:
        custom_store = InMemoryStore()
        manager = create_memory_manager(memory_store=custom_store)
        assert isinstance(manager, DefaultMemoryManager)

    def test_accepts_custom_event_bus(self) -> None:
        bus = InMemoryEventBus()
        manager = create_memory_manager(event_bus=bus)
        assert isinstance(manager, DefaultMemoryManager)

    def test_accepts_both_optional_params(self) -> None:
        store = InMemoryStore()
        bus = InMemoryEventBus()
        manager = create_memory_manager(memory_store=store, event_bus=bus)
        assert isinstance(manager, DefaultMemoryManager)


# ---------------------------------------------------------------------------
# create_session_manager
# ---------------------------------------------------------------------------


class TestCreateSessionManager:
    def test_returns_default_session_manager(self) -> None:
        session_mgr = create_session_manager()
        assert isinstance(session_mgr, DefaultSessionManager)

    def test_accepts_custom_memory_manager(self) -> None:
        manager = create_memory_manager()
        session_mgr = create_session_manager(memory_manager=manager)
        assert isinstance(session_mgr, DefaultSessionManager)
