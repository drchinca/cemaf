"""
Memory module - Short-term and long-term memory management.

Memory types:
- SESSION: In-memory, single run (short-term)
- PERSISTENT: Stored in DB, survives runs (long-term)

Memory scopes:
- TENANT: tenant-level knowledge (shared across all projects)
- PROJECT: Project-specific knowledge
- AUDIENCE_SEGMENT: Segment-specific knowledge
- PLATFORM: Platform-specific knowledge
- PERSONAE: Persona-specific knowledge
- CONVERSATION: Conversation-scoped (cleared after each conversation)
- TURN: Turn-scoped (cleared after each turn)

## Configuration

Settings for this module are defined in MemorySettings.

Environment Variables:
    CEMAF_MEMORY_BACKEND: Store backend ("memory", "json_file", "sqlite", "postgres", or registered custom)
    CEMAF_MEMORY_DEFAULT_TTL_SECONDS: Default TTL for memory items (default: 3600)
    CEMAF_MEMORY_MAX_ITEMS: Max items in memory store (default: 10000)
    CEMAF_MEMORY_FILE_PATH: JSON file path for json_file backend
    CEMAF_MEMORY_SQLITE_PATH: SQLite database path for sqlite backend
    CEMAF_POSTGRES_DSN: PostgreSQL DSN for postgres backend

## Usage

Protocol-based:
    >>> from cemaf.memory import MemoryStore, MemoryItem
    >>> from cemaf.core.enums import MemoryScope
    >>> from cemaf.core.types import Confidence
    >>>
    >>> class MyMemoryStore:
    ...     async def get(self, scope: MemoryScope, key: str) -> MemoryItem | None:
    ...         # Your implementation
    ...         ...
    ...
    ...     async def set(self, item: MemoryItem) -> None:
    ...         # Your implementation
    ...         ...

Built-in Implementation:
    >>> from cemaf.memory import InMemoryStore
    >>> store = InMemoryStore()
    >>> item = MemoryItem(
    ...     scope=MemoryScope.TENANT,
    ...     key="company",
    ...     value={"name": "Acme"}
    ... )
    >>> await store.set(item)

## Extension

Memory store implementations are protocol-first. Inject any object that
implements MemoryStore directly, or register a factory with
memory_store_registry.register(...) so create_memory_store() and env-driven
configuration can instantiate it.

See cemaf.memory.protocols.MemoryStore for the protocol definition.
"""
# mypy: disable-error-code="attr-defined"

# Built-in implementations
from cemaf.memory.base import InMemoryStore
from cemaf.memory.compaction import (
    CompactedMemory,
    CompactionLevel,
    MemoryCompactor,
    SimpleMemoryCompactor,
)
from cemaf.memory.context_provider import (
    DefaultMemoryContextProvider,
    MemoryContextProvider,
)
from cemaf.memory.deduplication import (
    DeduplicationAction,
    DeduplicationResult,
    DuplicateMatch,
    MatchType,
    MemoryDeduplicator,
    SemanticDeduplicator,
)
from cemaf.memory.episodic import (
    Episode,
    EpisodicEvent,
    EpisodicStore,
    InMemoryEpisodicStore,
)
from cemaf.memory.extraction import (
    ExtractedMemory,
    ExtractionCategory,
    MemoryExtractor,
    PrefixedMemoryEmitter,
    RuleBasedExtractor,
    normalize_mapping_values,
    normalize_string_list,
    parse_structured_session_output,
    slug_memory_signal,
)
from cemaf.memory.extraction_pipeline import ExtractionPipeline, ExtractionReport
from cemaf.memory.factories import (
    MemoryRuntime,
    create_extraction_pipeline,
    create_memory_compactor,
    create_memory_context_provider,
    create_memory_extractor,
    create_memory_manager,
    create_memory_runtime,
    create_memory_scorer,
    create_memory_store,
    create_memory_store_from_config,
    create_scope_scorer,
    create_session_manager,
    create_tiered_store,
    memory_compactor_registry,
    memory_extractor_registry,
    memory_scorer_registry,
    memory_store_registry,
)
from cemaf.memory.manager import DefaultMemoryManager, MemoryManager
from cemaf.memory.protocols import MemoryItem, MemoryStore
from cemaf.memory.scope_hierarchy import (
    PropagatingScorer,
    ScopeNode,
    ScopePath,
    ScopeScorer,
)
from cemaf.memory.scoring import (
    DecayFunction,
    MemoryScorer,
    ScoredMemoryItem,
    ScoringWeights,
    TemporalDecayScorer,
)
from cemaf.memory.semantic import (
    DefaultSemanticMemoryStore,
    MemoryQuery,
    MemorySearchResult,
    SemanticMemoryStore,
)
from cemaf.memory.session import (
    DefaultSessionManager,
    ReportingSessionManager,
    SessionDisposalReport,
    SessionManager,
    SessionPhase,
    SessionState,
)
from cemaf.memory.sqlite_store import (
    SqliteMemoryStore,
    load_items_by_scopes,
    load_items_by_scopes_sync,
)
from cemaf.memory.tiered import (
    LoadingTier,
    TieredMemoryItem,
    TierGenerator,
    TruncationTierGenerator,
)
from cemaf.memory.tiered_store import TieredMemoryStore

__all__ = [
    # Core
    "MemoryItem",
    "MemoryStore",
    "InMemoryStore",
    "SqliteMemoryStore",
    "load_items_by_scopes",
    "load_items_by_scopes_sync",
    # Scoring
    "DecayFunction",
    "MemoryScorer",
    "ScoredMemoryItem",
    "ScoringWeights",
    "TemporalDecayScorer",
    # Episodic
    "Episode",
    "EpisodicEvent",
    "EpisodicStore",
    "InMemoryEpisodicStore",
    # Extraction
    "ExtractionCategory",
    "ExtractedMemory",
    "ExtractionPipeline",
    "ExtractionReport",
    "MemoryExtractor",
    "PrefixedMemoryEmitter",
    "normalize_mapping_values",
    "normalize_string_list",
    "parse_structured_session_output",
    "RuleBasedExtractor",
    "slug_memory_signal",
    # Semantic bridge
    "DefaultSemanticMemoryStore",
    "MemoryQuery",
    "MemorySearchResult",
    "SemanticMemoryStore",
    # Manager
    "DefaultMemoryManager",
    "MemoryManager",
    "MemoryRuntime",
    # Context bridge
    "DefaultMemoryContextProvider",
    "MemoryContextProvider",
    # Compaction
    "CompactedMemory",
    "CompactionLevel",
    "MemoryCompactor",
    "SimpleMemoryCompactor",
    # Session lifecycle
    "DefaultSessionManager",
    "ReportingSessionManager",
    "SessionManager",
    "SessionDisposalReport",
    "SessionPhase",
    "SessionState",
    # Scope hierarchy
    "PropagatingScorer",
    "ScopeNode",
    "ScopePath",
    "ScopeScorer",
    # Tiered loading
    "LoadingTier",
    "TierGenerator",
    "TieredMemoryItem",
    "TieredMemoryStore",
    "TruncationTierGenerator",
    # Deduplication
    "DeduplicationAction",
    "DeduplicationResult",
    "DuplicateMatch",
    "MatchType",
    "MemoryDeduplicator",
    "SemanticDeduplicator",
    # Factories
    "create_memory_compactor",
    "create_extraction_pipeline",
    "create_memory_extractor",
    "create_memory_runtime",
    "create_memory_context_provider",
    "create_memory_manager",
    "create_memory_scorer",
    "create_memory_store",
    "create_memory_store_from_config",
    "create_scope_scorer",
    "create_session_manager",
    "create_tiered_store",
    "memory_compactor_registry",
    "memory_extractor_registry",
    "memory_scorer_registry",
    "memory_store_registry",
]
