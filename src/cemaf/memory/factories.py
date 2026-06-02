"""
Factory functions for memory store components.

Provides convenient ways to create memory stores with sensible defaults
while maintaining dependency injection principles.

Extension Point:
    This module is designed for extension. The create_memory_store_from_config()
    function includes a clear "EXTEND HERE" section where you can add
    your own memory backend implementations (Redis, PostgreSQL, DynamoDB, etc.).
"""

import os
from pathlib import Path
from typing import TYPE_CHECKING

from cemaf.config.protocols import Settings
from cemaf.core.enums import MemoryBackend
from cemaf.events.protocols import EventBus
from cemaf.memory.base import InMemoryStore, JsonFileMemoryStore
from cemaf.memory.compaction import SimpleMemoryCompactor
from cemaf.memory.deduplication import MemoryDeduplicator
from cemaf.memory.episodic import InMemoryEpisodicStore
from cemaf.memory.extraction import MemoryExtractor, RuleBasedExtractor
from cemaf.memory.extraction_pipeline import ExtractionPipeline
from cemaf.memory.manager import DefaultMemoryManager, MemoryManager
from cemaf.memory.protocols import MemoryStore
from cemaf.memory.scope_hierarchy import PropagatingScorer
from cemaf.memory.scoring import TemporalDecayScorer
from cemaf.memory.semantic import DefaultSemanticMemoryStore, SemanticMemoryStore
from cemaf.memory.session import DefaultSessionManager
from cemaf.memory.sqlite_store import SqliteMemoryStore
from cemaf.memory.tiered import TruncationTierGenerator
from cemaf.memory.tiered_store import TieredMemoryStore
from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider
from cemaf.retrieval.protocols import EmbeddingProvider, VectorStore

if TYPE_CHECKING:
    from cemaf.memory.postgres_session_manager import DistributedSessionManager
    from cemaf.memory.postgres_store import PostgresMemoryStore


def create_memory_store(
    backend: MemoryBackend | str = MemoryBackend.MEMORY,
    max_items: int = 10000,
    default_ttl_seconds: float = 3600.0,
    file_path: str | None = None,
) -> MemoryStore:
    """Build a `MemoryStore` for the given backend."""
    backend_enum = MemoryBackend(backend) if isinstance(backend, str) else backend
    match backend_enum:
        case MemoryBackend.MEMORY:
            return InMemoryStore()
        case MemoryBackend.JSON_FILE:
            path_str = file_path or os.getenv("CEMAF_MEMORY_FILE_PATH")
            if not path_str:
                raise ValueError(
                    f"{MemoryBackend.JSON_FILE.value} backend requires file_path "
                    f"(or CEMAF_MEMORY_FILE_PATH env)."
                )
            return JsonFileMemoryStore(path=Path(path_str))
        case MemoryBackend.SQLITE:
            db_path = os.getenv("CEMAF_MEMORY_SQLITE_PATH", "cemaf_memory.db")
            return SqliteMemoryStore(db_path=db_path)
        case MemoryBackend.POSTGRES:
            return create_postgres_memory_store()


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
    max_items = int(os.getenv("CEMAF_MEMORY_MAX_ITEMS", "10000"))
    default_ttl = float(os.getenv("CEMAF_MEMORY_DEFAULT_TTL_SECONDS", "3600.0"))

    try:
        backend = MemoryBackend(raw_backend)
    except ValueError:
        backend = None

    if backend is not None:
        return create_memory_store(
            backend=backend,
            max_items=max_items,
            default_ttl_seconds=default_ttl,
        )

    # ============================================================================
    # EXTEND HERE: Bring Your Own Memory Backend
    # ============================================================================
    # This is the extension point for custom memory backends.
    #
    # To add your own implementation:
    # 1. Implement the MemoryStore protocol (see cemaf.memory.protocols)
    # 2. Add your backend case below
    # 3. Read configuration from environment variables
    #
    # Example (Redis):
    #   elif backend == "redis":
    #       from your_package import RedisMemoryStore
    #
    #       redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    #       return RedisMemoryStore(
    #           url=redis_url,
    #           max_items=max_items,
    #           default_ttl_seconds=default_ttl,
    #       )
    #
    # Example (DynamoDB):
    #   elif backend == "dynamodb":
    #       from your_package import DynamoDBMemoryStore
    #
    #       table_name = os.getenv("DYNAMODB_MEMORY_TABLE", "cemaf_memory")
    #       region = os.getenv("AWS_REGION", "us-east-1")
    #
    #       return DynamoDBMemoryStore(
    #           table_name=table_name,
    #           region=region,
    #       )
    # ============================================================================

    supported = ", ".join(b.value for b in MemoryBackend)
    raise ValueError(
        f"Unsupported memory backend: {raw_backend}. "
        f"Supported: {supported}. "
        f"To add your own, extend create_memory_store_from_config() "
        f"in cemaf/memory/factories.py"
    )


def create_memory_manager(
    *,
    memory_store: MemoryStore | None = None,
    event_bus: EventBus | None = None,
    deduplicator: MemoryDeduplicator | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    vector_store: VectorStore | None = None,
) -> DefaultMemoryManager:
    """Create a fully wired DefaultMemoryManager."""
    store = memory_store or InMemoryStore()
    provider = embedding_provider or MockEmbeddingProvider()
    scorer = TemporalDecayScorer()
    vs = vector_store or InMemoryVectorStore(embedding_provider=provider)

    semantic_store = DefaultSemanticMemoryStore(
        memory_store=store,
        vector_store=vs,
        embedding_provider=provider,
        scorer=scorer,
    )
    episodic_store = InMemoryEpisodicStore()

    return DefaultMemoryManager(
        semantic_store=semantic_store,
        episodic_store=episodic_store,
        event_bus=event_bus,
        deduplicator=deduplicator,
    )


def create_session_manager(
    *,
    memory_manager: DefaultMemoryManager | None = None,
    extraction_pipeline: ExtractionPipeline | None = None,
) -> DefaultSessionManager:
    """Create a DefaultSessionManager with default compactor and optional extraction."""
    manager = memory_manager or create_memory_manager()
    scorer = TemporalDecayScorer()
    compactor = SimpleMemoryCompactor(scorer=scorer)

    return DefaultSessionManager(
        memory_manager=manager,
        compactor=compactor,
        extraction_pipeline=extraction_pipeline,
    )


def create_tiered_store(
    *,
    memory_store: MemoryStore | None = None,
) -> TieredMemoryStore:
    """Create a TieredMemoryStore with default tier generator."""
    store = memory_store or InMemoryStore()
    embedding_provider = MockEmbeddingProvider()
    scorer = TemporalDecayScorer()

    semantic_store = DefaultSemanticMemoryStore(
        memory_store=store,
        vector_store=InMemoryVectorStore(embedding_provider=embedding_provider),
        embedding_provider=embedding_provider,
        scorer=scorer,
    )

    return TieredMemoryStore(
        semantic_store=semantic_store,
        tier_generator=TruncationTierGenerator(),
    )


def create_extraction_pipeline(
    *,
    memory_manager: MemoryManager,
    extractor: MemoryExtractor | None = None,
    deduplicator: MemoryDeduplicator | None = None,
    event_bus: EventBus | None = None,
) -> ExtractionPipeline:
    """Create an ExtractionPipeline with defaults."""
    return ExtractionPipeline(
        extractor=extractor or RuleBasedExtractor(),
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
    scorer = TemporalDecayScorer()
    compactor = SimpleMemoryCompactor(scorer=scorer)
    session_store = RedisSessionStore(redis_url=resolved_url)
    return DistributedSessionManager(
        memory_manager=manager,
        compactor=compactor,
        session_store=session_store,
        extraction_pipeline=extraction_pipeline,
    )
