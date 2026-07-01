"""Tests for memory factory functions."""

from pathlib import Path

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.events.bus import InMemoryEventBus
from cemaf.memory.base import InMemoryStore, MemoryItem
from cemaf.memory.compaction import CompactedMemory, CompactionLevel, MemoryCompactor
from cemaf.memory.episodic import Episode, EpisodicEvent, InMemoryEpisodicStore
from cemaf.memory.extraction import RuleBasedExtractor
from cemaf.memory.factories import (
    create_memory_compactor,
    create_memory_extractor,
    create_memory_manager,
    create_memory_runtime,
    create_memory_scorer,
    create_memory_store,
    create_memory_store_from_config,
    create_session_manager,
    memory_compactor_registry,
    memory_extractor_registry,
    memory_scorer_registry,
    memory_store_registry,
)
from cemaf.memory.manager import DefaultMemoryManager
from cemaf.memory.scoring import MemoryScorer, ScoredMemoryItem, TemporalDecayScorer
from cemaf.memory.session import DefaultSessionManager, ReportingSessionManager

# ---------------------------------------------------------------------------
# create_memory_store
# ---------------------------------------------------------------------------


class CustomMemoryScorer:
    def score(
        self,
        item: MemoryItem,
        *,
        access_count: int = 0,
        relevance: float = 0.0,
    ) -> ScoredMemoryItem:
        return ScoredMemoryItem(
            item=item,
            score=0.5,
            recency_score=0.5,
            confidence_score=float(item.confidence),
            frequency_score=0.0,
            relevance_score=relevance,
        )

    def score_batch(
        self,
        items: tuple[MemoryItem, ...],
        *,
        access_counts: dict[str, int] | None = None,
    ) -> tuple[ScoredMemoryItem, ...]:
        return tuple(self.score(item=item) for item in items)


class CustomMemoryCompactor:
    async def compact(
        self,
        item: MemoryItem,
        *,
        target_level: CompactionLevel,
    ) -> CompactedMemory:
        return CompactedMemory(
            item=item,
            level=target_level,
            original_token_count=1,
            compacted_token_count=1,
        )

    async def compact_batch_to_budget(
        self,
        items: tuple[MemoryItem, ...],
        *,
        token_budget: int,
    ) -> tuple[CompactedMemory, ...]:
        return tuple(
            CompactedMemory(
                item=item,
                level=CompactionLevel.METADATA_ONLY,
                original_token_count=1,
                compacted_token_count=1,
            )
            for item in items[:token_budget]
        )


class CustomMemoryExtractor:
    async def extract(
        self,
        *,
        session_memories: tuple[MemoryItem, ...],
        episodes: tuple[Episode, ...],
        recent_events: tuple[EpisodicEvent, ...],
    ) -> tuple:
        return ()


class TestCreateMemoryStore:
    def test_valid_backend_returns_in_memory_store(self) -> None:
        store = create_memory_store(backend="memory")
        assert isinstance(store, InMemoryStore)

    def test_default_backend_returns_in_memory_store(self) -> None:
        store = create_memory_store()
        assert isinstance(store, InMemoryStore)

    def test_invalid_backend_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unsupported memory_store backend: redis"):
            create_memory_store(backend="redis")

    def test_custom_parameters_accepted(self) -> None:
        store = create_memory_store(
            backend="memory",
            max_items=5000,
            default_ttl_seconds=7200.0,
        )
        assert isinstance(store, InMemoryStore)

    @pytest.mark.asyncio
    async def test_memory_backend_applies_default_ttl(self) -> None:
        store = create_memory_store(
            backend="memory",
            max_items=None,
            default_ttl_seconds=30.0,
        )

        await store.set(MemoryItem(scope=MemoryScope.SESSION, key="k", value={"v": 1}))

        item = await store.get(MemoryScope.SESSION, "k")
        assert item is not None
        assert item.ttl is not None
        assert item.ttl.total_seconds() == pytest.approx(30.0)
        assert item.expires_at is not None

    @pytest.mark.asyncio
    async def test_memory_backend_honors_max_items(self) -> None:
        store = create_memory_store(
            backend="memory",
            max_items=2,
            default_ttl_seconds=None,
        )

        await store.set(MemoryItem(scope=MemoryScope.SESSION, key="one", value={}))
        await store.set(MemoryItem(scope=MemoryScope.SESSION, key="two", value={}))
        await store.set(MemoryItem(scope=MemoryScope.SESSION, key="three", value={}))

        items = await store.list_by_scope(MemoryScope.SESSION)
        assert tuple(item.key for item in items) == ("two", "three")

    def test_sqlite_backend_accepts_explicit_db_path(self, tmp_path: Path) -> None:
        store = create_memory_store(backend="sqlite", db_path=str(tmp_path / "memory.db"))
        assert store.__class__.__name__ == "SqliteMemoryStore"

    def test_postgres_backend_passes_connection_options(self, monkeypatch: pytest.MonkeyPatch) -> None:
        created: dict[str, object] = {}
        fake_store = object()

        def _fake_create_postgres_memory_store(**kwargs):
            created["postgres_args"] = kwargs
            return fake_store

        monkeypatch.setattr(
            "cemaf.memory.factories.create_postgres_memory_store",
            _fake_create_postgres_memory_store,
        )

        store = create_memory_store(
            backend="postgres",
            dsn="postgresql://example/cemaf",
            tenant_id="tenant-a",
        )

        assert store is fake_store
        assert created["postgres_args"] == {
            "dsn": "postgresql://example/cemaf",
            "tenant_id": "tenant-a",
            "pool_min": 2,
            "pool_max": 10,
            "schema": "cemaf",
        }

    def test_supports_custom_registered_backend(self) -> None:
        created: dict[str, object] = {}

        def _factory(**kwargs):
            created["args"] = kwargs
            return InMemoryStore()

        memory_store_registry.register(backend="custom-test-memory-store", factory=_factory)

        store = create_memory_store(
            backend="custom-test-memory-store",
            max_items=123,
            default_ttl_seconds=45.0,
            custom_flag=True,
        )

        assert isinstance(store, InMemoryStore)
        assert created["args"]["max_items"] == 123
        assert created["args"]["default_ttl_seconds"] == 45.0
        assert created["args"]["custom_flag"] is True


class TestMemoryComponentFactories:
    def test_create_memory_scorer_returns_builtin_scorer(self) -> None:
        scorer = create_memory_scorer(
            scorer_type="temporal_decay",
            decay_function="linear",
            half_life_seconds=1800.0,
        )

        assert isinstance(scorer, TemporalDecayScorer)

    def test_create_memory_scorer_supports_custom_registered_backend(self) -> None:
        created: dict[str, object] = {}

        def _factory(**kwargs):
            created["args"] = kwargs
            return CustomMemoryScorer()

        memory_scorer_registry.register(backend="custom-test-scorer", factory=_factory)

        scorer = create_memory_scorer("custom-test-scorer", mode="strict")

        assert isinstance(scorer, MemoryScorer)
        assert created["args"]["mode"] == "strict"

    def test_create_memory_compactor_supports_custom_registered_backend(self) -> None:
        created: dict[str, object] = {}
        scorer = CustomMemoryScorer()

        def _factory(**kwargs):
            created["args"] = kwargs
            return CustomMemoryCompactor()

        memory_compactor_registry.register(backend="custom-test-compactor", factory=_factory)

        compactor = create_memory_compactor("custom-test-compactor", scorer=scorer, mode="fast")

        assert isinstance(compactor, MemoryCompactor)
        assert created["args"]["scorer"] is scorer
        assert created["args"]["mode"] == "fast"

    def test_create_memory_extractor_supports_custom_registered_backend(self) -> None:
        created: dict[str, object] = {}

        def _factory(**kwargs):
            created["args"] = kwargs
            return CustomMemoryExtractor()

        memory_extractor_registry.register(backend="custom-test-extractor", factory=_factory)

        extractor = create_memory_extractor("custom-test-extractor", min_confidence=0.9)

        assert isinstance(extractor, CustomMemoryExtractor)
        assert created["args"]["min_confidence"] == 0.9


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

        with pytest.raises(ValueError, match="Unsupported memory_store backend: cassandra"):
            create_memory_store_from_config()

    def test_error_message_mentions_registry_extension_point(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CEMAF_MEMORY_BACKEND", "dynamodb")

        with pytest.raises(ValueError, match="memory_store_registry.register"):
            create_memory_store_from_config()

    def test_custom_registered_backend_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        created: dict[str, object] = {}

        def _factory(**kwargs):
            created["args"] = kwargs
            return InMemoryStore()

        memory_store_registry.register(backend="env-custom-memory-store", factory=_factory)
        monkeypatch.setenv("CEMAF_MEMORY_BACKEND", "env-custom-memory-store")
        monkeypatch.setenv("CEMAF_MEMORY_MAX_ITEMS", "77")
        monkeypatch.setenv("CEMAF_MEMORY_DEFAULT_TTL_SECONDS", "9.5")

        store = create_memory_store_from_config()

        assert isinstance(store, InMemoryStore)
        assert created["args"]["max_items"] == 77
        assert created["args"]["default_ttl_seconds"] == 9.5


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

    def test_accepts_custom_scorer_and_episodic_store(self) -> None:
        scorer = CustomMemoryScorer()
        episodic_store = InMemoryEpisodicStore()

        manager = create_memory_manager(scorer=scorer, episodic_store=episodic_store)

        assert manager._semantic._scorer is scorer  # noqa: SLF001
        assert manager._episodic is episodic_store  # noqa: SLF001

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

    def test_supports_registered_compactor_backend(self) -> None:
        memory_compactor_registry.register(
            backend="session-custom-compactor",
            factory=lambda **_: CustomMemoryCompactor(),
        )

        session_mgr = create_session_manager(compactor_type="session-custom-compactor")

        assert isinstance(session_mgr._compactor, CustomMemoryCompactor)  # noqa: SLF001


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
            "dsn": None,
            "tenant_id": "default",
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
            "scorer": created["memory_manager_args"]["scorer"],
        }
        assert isinstance(created["memory_manager_args"]["scorer"], TemporalDecayScorer)
        assert isinstance(created["extraction_pipeline_args"]["extractor"], RuleBasedExtractor)
        assert created["extraction_pipeline_args"]["memory_manager"] is fake_memory_manager
        assert created["extraction_pipeline_args"]["extractor_type"] == "rule_based"
        assert created["extraction_pipeline_args"]["event_bus"] is fake_event_bus
        assert created["session_manager_args"] == {
            "memory_manager": fake_memory_manager,
            "extraction_pipeline": fake_extraction_pipeline,
            "compactor": created["session_manager_args"]["compactor"],
            "session_manager_cls": ReportingSessionManager,
        }
        assert isinstance(created["session_manager_args"]["compactor"], MemoryCompactor)
        assert created["subscribe_args"] == {
            "event_bus": fake_event_bus,
            "memory_manager": fake_memory_manager,
            "session_manager": fake_session_manager,
        }

    def test_requires_event_bus_when_subscription_enabled(self) -> None:
        with pytest.raises(ValueError, match="event_bus is required"):
            create_memory_runtime(subscribe_session_recording=True)

    def test_passes_postgres_options_to_memory_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        created: dict[str, object] = {}

        def _fake_create_embedding_provider(provider="mock", **kwargs):
            return object()

        def _fake_create_memory_store(backend="memory", **kwargs):
            created["memory_store_args"] = {"backend": backend, **kwargs}
            return object()

        def _fake_create_vector_store(backend="memory", **kwargs):
            return object()

        def _fake_create_memory_manager(**kwargs):
            return object()

        def _fake_create_extraction_pipeline(**kwargs):
            return object()

        def _fake_create_session_manager(**kwargs):
            return object()

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

        create_memory_runtime(
            memory_backend="postgres",
            dsn="postgresql://example/cemaf",
            tenant_id="tenant-a",
        )

        assert created["memory_store_args"] == {
            "backend": "postgres",
            "file_path": None,
            "db_path": None,
            "dsn": "postgresql://example/cemaf",
            "tenant_id": "tenant-a",
        }
