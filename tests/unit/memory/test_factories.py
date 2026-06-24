"""Tests for memory factory functions."""

from pathlib import Path

import pytest

from cemaf.events.bus import InMemoryEventBus
from cemaf.memory.base import InMemoryStore
from cemaf.memory.extraction import RuleBasedExtractor
from cemaf.memory.factories import (
    create_memory_manager,
    create_memory_runtime,
    create_memory_store,
    create_memory_store_from_config,
    create_session_manager,
)
from cemaf.memory.manager import DefaultMemoryManager
from cemaf.memory.session import DefaultSessionManager, ReportingSessionManager

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

    def test_sqlite_backend_accepts_explicit_db_path(self, tmp_path: Path) -> None:
        store = create_memory_store(backend="sqlite", db_path=str(tmp_path / "memory.db"))
        assert store.__class__.__name__ == "SqliteMemoryStore"


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

    def test_supports_reporting_session_manager(self) -> None:
        manager = create_memory_manager()
        session_mgr = create_session_manager(
            memory_manager=manager,
            session_manager_cls=ReportingSessionManager,
        )
        assert isinstance(session_mgr, ReportingSessionManager)


class TestCreateMemoryRuntime:
    def test_builds_sqlite_runtime_with_subscription(self, monkeypatch: pytest.MonkeyPatch) -> None:
        created: dict[str, object] = {}
        fake_event_bus = object()
        fake_embedding_provider = object()
        fake_memory_store = object()
        fake_vector_store = object()
        fake_memory_manager = object()
        fake_extraction_pipeline = object()
        fake_session_manager = object()

        def _fake_create_embedding_provider(provider="mock", **kwargs):
            created["embedding_provider_args"] = {"provider": provider, **kwargs}
            return fake_embedding_provider

        def _fake_create_memory_store(backend="memory", **kwargs):
            created["memory_store_args"] = {"backend": backend, **kwargs}
            return fake_memory_store

        def _fake_create_vector_store(backend="memory", **kwargs):
            created["vector_store_args"] = {"backend": backend, **kwargs}
            return fake_vector_store

        def _fake_create_memory_manager(**kwargs):
            created["memory_manager_args"] = kwargs
            return fake_memory_manager

        def _fake_create_extraction_pipeline(**kwargs):
            created["extraction_pipeline_args"] = kwargs
            return fake_extraction_pipeline

        def _fake_create_session_manager(**kwargs):
            created["session_manager_args"] = kwargs
            return fake_session_manager

        def _fake_subscribe_session_memory_recording(**kwargs):
            created["subscribe_args"] = kwargs

        monkeypatch.setattr(
            "cemaf.memory.factories.create_embedding_provider",
            _fake_create_embedding_provider,
        )
        monkeypatch.setattr("cemaf.memory.factories.create_memory_store", _fake_create_memory_store)
        monkeypatch.setattr("cemaf.memory.factories.create_vector_store", _fake_create_vector_store)
        monkeypatch.setattr(
            "cemaf.memory.factories.create_memory_manager",
            _fake_create_memory_manager,
        )
        monkeypatch.setattr(
            "cemaf.memory.factories.create_extraction_pipeline",
            _fake_create_extraction_pipeline,
        )
        monkeypatch.setattr(
            "cemaf.memory.factories.create_session_manager",
            _fake_create_session_manager,
        )
        monkeypatch.setattr(
            "cemaf.events.memory_subscriber.subscribe_session_memory_recording",
            _fake_subscribe_session_memory_recording,
        )

        runtime = create_memory_runtime(
            event_bus=fake_event_bus,  # type: ignore[arg-type]
            extractor=RuleBasedExtractor(),
            memory_backend="sqlite",
            vector_backend="sqlite",
            embedding_provider_name="hash",
            embedding_dimension=256,
            db_path="runtime.db",
            session_manager_cls=ReportingSessionManager,
            subscribe_session_recording=True,
        )

        assert runtime.embedding_provider is fake_embedding_provider
        assert runtime.memory_store is fake_memory_store
        assert runtime.vector_store is fake_vector_store
        assert runtime.memory_manager is fake_memory_manager
        assert runtime.extraction_pipeline is fake_extraction_pipeline
        assert runtime.session_manager is fake_session_manager
        assert created["embedding_provider_args"] == {
            "provider": "hash",
            "model": None,
            "dimension": 256,
            "api_key": None,
            "inference_provider": "hf-inference",
            "timeout_seconds": 60.0,
        }
        assert created["memory_store_args"] == {
            "backend": "sqlite",
            "file_path": None,
            "db_path": "runtime.db",
        }
        assert created["vector_store_args"] == {
            "backend": "sqlite",
            "embedding_provider": fake_embedding_provider,
            "dimension": 256,
            "db_path": "runtime.db",
            "dsn": None,
            "tenant_id": "default",
        }
        assert created["memory_manager_args"] == {
            "memory_store": fake_memory_store,
            "event_bus": fake_event_bus,
            "deduplicator": None,
            "embedding_provider": fake_embedding_provider,
            "vector_store": fake_vector_store,
        }
        assert isinstance(created["extraction_pipeline_args"]["extractor"], RuleBasedExtractor)
        assert created["extraction_pipeline_args"]["memory_manager"] is fake_memory_manager
        assert created["extraction_pipeline_args"]["event_bus"] is fake_event_bus
        assert created["session_manager_args"] == {
            "memory_manager": fake_memory_manager,
            "extraction_pipeline": fake_extraction_pipeline,
            "compactor": None,
            "session_manager_cls": ReportingSessionManager,
        }
        assert created["subscribe_args"] == {
            "event_bus": fake_event_bus,
            "memory_manager": fake_memory_manager,
            "session_manager": fake_session_manager,
        }

    def test_requires_event_bus_when_subscription_enabled(self) -> None:
        with pytest.raises(ValueError, match="event_bus is required"):
            create_memory_runtime(subscribe_session_recording=True)
