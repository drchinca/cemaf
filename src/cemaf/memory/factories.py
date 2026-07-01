"""
Factory functions for memory store components.

Provides convenient ways to create memory stores with sensible defaults
while maintaining dependency injection principles.

Extension Point:
    Register custom memory backends with memory_store_registry.register(...).
"""
# mypy: disable-error-code="attr-defined"

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cemaf.config.protocols import Settings
from cemaf.context.compiler import ContextCompiler, TokenEstimator
from cemaf.context.factories import create_priority_compiler, create_token_estimator
from cemaf.core.enums import MemoryBackend
from cemaf.core.provider_registry import ProviderRegistry
from cemaf.events.protocols import EventBus
from cemaf.memory.base import InMemoryStore, JsonFileMemoryStore
from cemaf.memory.compaction import MemoryCompactor, SimpleMemoryCompactor
from cemaf.memory.context_provider import DefaultMemoryContextProvider
from cemaf.memory.deduplication import MemoryDeduplicator
from cemaf.memory.episodic import EpisodicStore, InMemoryEpisodicStore
from cemaf.memory.extraction import MemoryExtractor, RuleBasedExtractor
from cemaf.memory.extraction_pipeline import ExtractionPipeline
from cemaf.memory.manager import DefaultMemoryManager, MemoryManager
from cemaf.memory.protocols import MemoryStore
from cemaf.memory.scope_hierarchy import PropagatingScorer
from cemaf.memory.scoring import DecayFunction, MemoryScorer, ScoringWeights, TemporalDecayScorer
from cemaf.memory.semantic import DefaultSemanticMemoryStore, SemanticMemoryStore
from cemaf.memory.session import DefaultSessionManager, SessionManager
from cemaf.memory.sqlite_store import SqliteMemoryStore
from cemaf.memory.tiered import TruncationTierGenerator
from cemaf.memory.tiered_store import TieredMemoryStore
from cemaf.retrieval.factories import create_embedding_provider, create_vector_store
from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider
from cemaf.retrieval.protocols import EmbeddingProvider, VectorStore

if TYPE_CHECKING:
    from cemaf.memory.postgres_session_manager import DistributedSessionManager
    from cemaf.memory.postgres_store import PostgresMemoryStore


memory_store_registry: ProviderRegistry[MemoryStore] = ProviderRegistry(name="memory_store")
memory_scorer_registry: ProviderRegistry[MemoryScorer] = ProviderRegistry(name="memory_scorer")
memory_compactor_registry: ProviderRegistry[MemoryCompactor] = ProviderRegistry(name="memory_compactor")
memory_extractor_registry: ProviderRegistry[MemoryExtractor] = ProviderRegistry(name="memory_extractor")


@dataclass(frozen=True)
class MemoryRuntime:
    """Bundled memory runtime dependencies produced by framework factories."""

    embedding_provider: EmbeddingProvider
    memory_store: MemoryStore
    vector_store: VectorStore
    memory_manager: DefaultMemoryManager
    extraction_pipeline: ExtractionPipeline
    session_manager: SessionManager


def _create_in_memory_store(**kwargs: Any) -> MemoryStore:
    return InMemoryStore(
        max_items=int(kwargs["max_items"]) if kwargs.get("max_items") is not None else None,
        default_ttl_seconds=(
            float(kwargs["default_ttl_seconds"]) if kwargs.get("default_ttl_seconds") is not None else None
        ),
    )


def _create_json_file_memory_store(**kwargs: Any) -> MemoryStore:
    path_str = kwargs.get("file_path") or os.getenv("CEMAF_MEMORY_FILE_PATH")
    if not path_str:
        raise ValueError(
            f"{MemoryBackend.JSON_FILE.value} backend requires file_path (or CEMAF_MEMORY_FILE_PATH env)."
        )
    return JsonFileMemoryStore(path=Path(str(path_str)))


def _create_sqlite_memory_store(**kwargs: Any) -> MemoryStore:
    sqlite_path = kwargs.get("db_path") or os.getenv("CEMAF_MEMORY_SQLITE_PATH") or "cemaf_memory.db"
    return SqliteMemoryStore(db_path=str(sqlite_path))


def _create_postgres_memory_store(**kwargs: Any) -> MemoryStore:
    return create_postgres_memory_store(
        dsn=kwargs.get("dsn"),
        tenant_id=str(kwargs.get("tenant_id", "default")),
        pool_min=int(kwargs.get("pool_min", 2)),
        pool_max=int(kwargs.get("pool_max", 10)),
        schema=str(kwargs.get("schema", "cemaf")),
    )


memory_store_registry.register(backend=MemoryBackend.MEMORY.value, factory=_create_in_memory_store)
memory_store_registry.register(backend=MemoryBackend.JSON_FILE.value, factory=_create_json_file_memory_store)
memory_store_registry.register(backend=MemoryBackend.SQLITE.value, factory=_create_sqlite_memory_store)
memory_store_registry.register(backend=MemoryBackend.POSTGRES.value, factory=_create_postgres_memory_store)


def _create_temporal_decay_scorer(**kwargs: Any) -> MemoryScorer:
    weights = kwargs.get("weights")
    default_weights = ScoringWeights()
    if weights is None and any(
        kwargs.get(key) is not None
        for key in (
            "recency_weight",
            "confidence_weight",
            "frequency_weight",
            "relevance_weight",
        )
    ):
        weights = ScoringWeights(
            recency=float(kwargs.get("recency_weight", default_weights.recency)),
            confidence=float(kwargs.get("confidence_weight", default_weights.confidence)),
            frequency=float(kwargs.get("frequency_weight", default_weights.frequency)),
            relevance=float(kwargs.get("relevance_weight", default_weights.relevance)),
        )

    raw_decay = kwargs.get("decay_function", DecayFunction.EXPONENTIAL)
    decay_function = raw_decay if isinstance(raw_decay, DecayFunction) else DecayFunction(str(raw_decay))

    return TemporalDecayScorer(
        weights=weights,
        decay_function=decay_function,
        half_life_seconds=float(kwargs.get("half_life_seconds", 3600.0)),
        max_age_seconds=float(kwargs.get("max_age_seconds", 86400.0)),
        max_frequency=int(kwargs.get("max_frequency", 100)),
    )


def _create_simple_memory_compactor(**kwargs: Any) -> MemoryCompactor:
    scorer = kwargs.get("scorer") or create_memory_scorer()
    return SimpleMemoryCompactor(
        scorer=scorer,
        token_estimator=kwargs.get("token_estimator"),
        summary_max_chars=int(kwargs.get("summary_max_chars", 200)),
    )


def _create_rule_based_extractor(**kwargs: Any) -> MemoryExtractor:
    return RuleBasedExtractor(
        min_confidence=float(kwargs.get("min_confidence", 0.6)),
        min_event_importance=float(kwargs.get("min_event_importance", 0.7)),
    )


memory_scorer_registry.register(backend="temporal_decay", factory=_create_temporal_decay_scorer)
memory_compactor_registry.register(backend="simple", factory=_create_simple_memory_compactor)
memory_extractor_registry.register(backend="rule_based", factory=_create_rule_based_extractor)


def create_memory_store(
    backend: MemoryBackend | str = MemoryBackend.MEMORY,
    max_items: int | None = 10000,
    default_ttl_seconds: float | None = 3600.0,
    file_path: str | None = None,
    db_path: str | None = None,
    dsn: str | None = None,
    tenant_id: str = "default",
    **backend_options: Any,
) -> MemoryStore:
    """Build a `MemoryStore` for the given backend."""
    backend_name = backend.value if isinstance(backend, MemoryBackend) else str(backend)
    return memory_store_registry.create(
        backend=backend_name,
        max_items=max_items,
        default_ttl_seconds=default_ttl_seconds,
        file_path=file_path,
        db_path=db_path,
        dsn=dsn,
        tenant_id=tenant_id,
        **backend_options,
    )


def create_memory_scorer(
    scorer_type: str = "temporal_decay",
    **scorer_options: Any,
) -> MemoryScorer:
    """Build a `MemoryScorer` through the registry."""
    return memory_scorer_registry.create(backend=scorer_type, **scorer_options)


def create_memory_compactor(
    compactor_type: str = "simple",
    *,
    scorer: MemoryScorer | None = None,
    **compactor_options: Any,
) -> MemoryCompactor:
    """Build a `MemoryCompactor` through the registry."""
    return memory_compactor_registry.create(
        backend=compactor_type,
        scorer=scorer,
        **compactor_options,
    )


def create_memory_extractor(
    extractor_type: str = "rule_based",
    **extractor_options: Any,
) -> MemoryExtractor:
    """Build a `MemoryExtractor` through the registry."""
    return memory_extractor_registry.create(backend=extractor_type, **extractor_options)


def create_memory_store_from_config(settings: Settings | None = None) -> MemoryStore:
    """
    Create MemoryStore from environment configuration.

    Reads from environment variables:
    - CEMAF_MEMORY_BACKEND: Backend type (default: "memory")
    - CEMAF_MEMORY_MAX_ITEMS: Max items in store (default: 10000)
    - CEMAF_MEMORY_DEFAULT_TTL_SECONDS: Default TTL (default: 3600.0)
    - CEMAF_MEMORY_CLEANUP_INTERVAL_SECONDS: Cleanup interval (default: 300.0)

    Returns:
        Configured MemoryStore instance

    Example:
        # From environment
        store = create_memory_store_from_config()
    """
    raw_backend = os.getenv("CEMAF_MEMORY_BACKEND", MemoryBackend.MEMORY.value)
    max_items = int(
        os.getenv(
            "CEMAF_MEMORY_MAX_ITEMS",
            str(settings.memory.max_items if settings else 10000),
        )
    )
    default_ttl = float(
        os.getenv(
            "CEMAF_MEMORY_DEFAULT_TTL_SECONDS",
            str(settings.memory.default_ttl_seconds if settings else 3600.0),
        )
    )

    return create_memory_store(
        backend=raw_backend,
        max_items=max_items,
        default_ttl_seconds=default_ttl,
        file_path=os.getenv("CEMAF_MEMORY_FILE_PATH"),
        db_path=os.getenv("CEMAF_MEMORY_SQLITE_PATH"),
        dsn=os.getenv("CEMAF_POSTGRES_DSN"),
        tenant_id=os.getenv("CEMAF_TENANT_ID", "default"),
    )


def create_memory_manager(
    *,
    memory_store: MemoryStore | None = None,
    event_bus: EventBus | None = None,
    deduplicator: MemoryDeduplicator | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    vector_store: VectorStore | None = None,
    scorer: MemoryScorer | None = None,
    episodic_store: EpisodicStore | None = None,
) -> DefaultMemoryManager:
    """Create a fully wired DefaultMemoryManager."""
    store = memory_store or InMemoryStore()
    provider = embedding_provider or MockEmbeddingProvider()
    resolved_scorer = scorer or create_memory_scorer()
    vs = vector_store or InMemoryVectorStore(embedding_provider=provider)

    semantic_store = DefaultSemanticMemoryStore(
        memory_store=store,
        vector_store=vs,
        embedding_provider=provider,
        scorer=resolved_scorer,
    )
    resolved_episodic_store = episodic_store or InMemoryEpisodicStore()

    return DefaultMemoryManager(
        semantic_store=semantic_store,
        episodic_store=resolved_episodic_store,
        event_bus=event_bus,
        deduplicator=deduplicator,
    )


def create_session_manager(
    *,
    memory_manager: DefaultMemoryManager | None = None,
    extraction_pipeline: ExtractionPipeline | None = None,
    compactor: MemoryCompactor | None = None,
    compactor_type: str = "simple",
    scorer: MemoryScorer | None = None,
    session_manager_cls: type[DefaultSessionManager] = DefaultSessionManager,
) -> DefaultSessionManager:
    """Create a DefaultSessionManager with default compactor and optional extraction."""
    manager = memory_manager or create_memory_manager()
    resolved_compactor = compactor or create_memory_compactor(
        compactor_type=compactor_type,
        scorer=scorer,
    )

    return session_manager_cls(
        memory_manager=manager,
        compactor=resolved_compactor,
        extraction_pipeline=extraction_pipeline,
    )


def create_memory_runtime(
    *,
    event_bus: EventBus | None = None,
    extractor: MemoryExtractor | None = None,
    deduplicator: MemoryDeduplicator | None = None,
    memory_backend: MemoryBackend | str = MemoryBackend.MEMORY,
    vector_backend: str = "memory",
    embedding_provider_name: str = "mock",
    embedding_dimension: int = 384,
    embedding_model: str | None = None,
    embedding_api_key: str | None = None,
    embedding_inference_provider: str = "hf-inference",
    embedding_timeout_seconds: float = 60.0,
    scorer: MemoryScorer | None = None,
    scorer_type: str = "temporal_decay",
    extractor_type: str = "rule_based",
    compactor_type: str = "simple",
    file_path: str | None = None,
    db_path: str | None = None,
    dsn: str | None = None,
    tenant_id: str = "default",
    compactor: MemoryCompactor | None = None,
    session_manager_cls: type[DefaultSessionManager] = DefaultSessionManager,
    subscribe_session_recording: bool = False,
) -> MemoryRuntime:
    """Create a fully wired memory runtime bundle from storage/config choices."""
    embedding_provider = create_embedding_provider(
        provider=embedding_provider_name,
        model=embedding_model,
        dimension=embedding_dimension,
        api_key=embedding_api_key,
        inference_provider=embedding_inference_provider,
        timeout_seconds=embedding_timeout_seconds,
    )
    memory_store = create_memory_store(
        backend=memory_backend,
        file_path=file_path,
        db_path=db_path,
        dsn=dsn,
        tenant_id=tenant_id,
    )
    resolved_scorer = scorer or create_memory_scorer(scorer_type=scorer_type)
    vector_store = create_vector_store(
        backend=vector_backend,
        embedding_provider=embedding_provider,
        dimension=embedding_dimension,
        db_path=db_path,
        dsn=dsn,
        tenant_id=tenant_id,
    )
    memory_manager = create_memory_manager(
        memory_store=memory_store,
        event_bus=event_bus,
        deduplicator=deduplicator,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
        scorer=resolved_scorer,
    )
    extraction_pipeline = create_extraction_pipeline(
        memory_manager=memory_manager,
        extractor=extractor,
        extractor_type=extractor_type,
        deduplicator=deduplicator,
        event_bus=event_bus,
    )
    resolved_compactor = compactor or create_memory_compactor(
        compactor_type=compactor_type,
        scorer=resolved_scorer,
    )
    session_manager = create_session_manager(
        memory_manager=memory_manager,
        extraction_pipeline=extraction_pipeline,
        compactor=resolved_compactor,
        session_manager_cls=session_manager_cls,
    )
    if subscribe_session_recording:
        if event_bus is None:
            raise ValueError("event_bus is required when subscribe_session_recording=True")
        from cemaf.events.memory_subscriber import (
            subscribe_session_memory_recording,
        )

        subscribe_session_memory_recording(
            event_bus=event_bus,
            memory_manager=memory_manager,
            session_manager=session_manager,
        )
    return MemoryRuntime(
        embedding_provider=embedding_provider,
        memory_store=memory_store,
        vector_store=vector_store,
        memory_manager=memory_manager,
        extraction_pipeline=extraction_pipeline,
        session_manager=session_manager,
    )


def create_memory_context_provider(
    *,
    memory_manager: MemoryManager,
    compactor: MemoryCompactor | None = None,
    compiler: ContextCompiler | None = None,
    token_estimator: TokenEstimator | None = None,
    tiered_store: TieredMemoryStore | None = None,
    chars_per_token: float = 4.0,
    compactor_type: str = "simple",
    scorer: MemoryScorer | None = None,
) -> DefaultMemoryContextProvider:
    """Create a `DefaultMemoryContextProvider` — the JIT memory-to-context pull bridge.

    This is the recommended way to give nodes/agents *pull* access to accumulated
    knowledge: recall relevant memories, compact them to a token budget, and feed
    them into the context compiler — instead of pushing full history into prompts.
    """
    estimator = token_estimator or create_token_estimator(chars_per_token=chars_per_token)
    resolved_scorer = scorer or create_memory_scorer()
    return DefaultMemoryContextProvider(
        memory_manager=memory_manager,
        compactor=compactor
        or create_memory_compactor(
            compactor_type=compactor_type,
            scorer=resolved_scorer,
        ),
        compiler=compiler or create_priority_compiler(token_estimator=estimator),
        token_estimator=estimator,
        tiered_store=tiered_store,
    )


def create_tiered_store(
    *,
    memory_store: MemoryStore | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    vector_store: VectorStore | None = None,
    scorer: MemoryScorer | None = None,
) -> TieredMemoryStore:
    """Create a TieredMemoryStore with default tier generator."""
    store = memory_store or InMemoryStore()
    resolved_embedding_provider = embedding_provider or MockEmbeddingProvider()
    resolved_scorer = scorer or create_memory_scorer()

    semantic_store = DefaultSemanticMemoryStore(
        memory_store=store,
        vector_store=vector_store or InMemoryVectorStore(embedding_provider=resolved_embedding_provider),
        embedding_provider=resolved_embedding_provider,
        scorer=resolved_scorer,
    )

    return TieredMemoryStore(
        semantic_store=semantic_store,
        tier_generator=TruncationTierGenerator(),
    )


def create_extraction_pipeline(
    *,
    memory_manager: MemoryManager,
    extractor: MemoryExtractor | None = None,
    extractor_type: str = "rule_based",
    deduplicator: MemoryDeduplicator | None = None,
    event_bus: EventBus | None = None,
) -> ExtractionPipeline:
    """Create an ExtractionPipeline with defaults."""
    return ExtractionPipeline(
        extractor=extractor or create_memory_extractor(extractor_type=extractor_type),
        deduplicator=deduplicator,
        memory_manager=memory_manager,
        event_bus=event_bus,
    )


def create_scope_scorer(
    *,
    semantic_store: SemanticMemoryStore,
    propagation_factor: float = 0.7,
) -> PropagatingScorer:
    """Create a PropagatingScorer with configurable propagation."""
    return PropagatingScorer(
        semantic_store=semantic_store,
        propagation_factor=propagation_factor,
    )


def create_postgres_memory_store(
    *,
    dsn: str | None = None,
    tenant_id: str = "default",
    pool_min: int = 2,
    pool_max: int = 10,
    schema: str = "cemaf",
) -> PostgresMemoryStore:
    """Create a PostgresMemoryStore, reading DSN from env if not provided.

    Reads CEMAF_POSTGRES_DSN when dsn is None.
    Pool is initialized lazily on first I/O call.
    """
    resolved_dsn: str = dsn or os.getenv("CEMAF_POSTGRES_DSN") or "postgresql://localhost/cemaf"
    from cemaf.memory.postgres_store import PostgresMemoryStore

    return PostgresMemoryStore(
        dsn=resolved_dsn,
        tenant_id=tenant_id,
        pool_min=pool_min,
        pool_max=pool_max,
        schema=schema,
    )


def create_distributed_session_manager(
    *,
    redis_url: str | None = None,
    memory_manager: DefaultMemoryManager | None = None,
    extraction_pipeline: ExtractionPipeline | None = None,
) -> DistributedSessionManager:
    """Create a DistributedSessionManager with Redis-backed session state.

    Reads CEMAF_REDIS_URL from env when redis_url is None.
    """
    resolved_url: str = redis_url or os.getenv("CEMAF_REDIS_URL") or "redis://localhost:6379"
    from cemaf.memory.postgres_session_manager import DistributedSessionManager
    from cemaf.memory.redis_session_store import RedisSessionStore

    manager = memory_manager or create_memory_manager()
    scorer = create_memory_scorer()
    compactor = create_memory_compactor(scorer=scorer)
    session_store = RedisSessionStore(redis_url=resolved_url)
    return DistributedSessionManager(
        memory_manager=manager,
        compactor=compactor,
        session_store=session_store,
        extraction_pipeline=extraction_pipeline,
    )
