"""Knowledge graph module — entity/relation modeling and graph queries."""

from cemaf.knowledge.factories import create_knowledge_graph, knowledge_graph_registry
from cemaf.knowledge.graph import MemoryBackedKnowledgeGraph
from cemaf.knowledge.hub_spoke import (
    KG_INVALIDATION_EVENT_TYPE,
    HubKnowledgeGraph,
    InvalidationKind,
    KGInvalidationEvent,
    LocalSpokeCache,
    SpokeCacheConfig,
    SpokeReadHubWriteKG,
    SpokeStats,
    create_hub_spoke_kg,
)
from cemaf.knowledge.models import (
    EntityType,
    KGBranchDiff,
    KGBranchRef,
    KGEntity,
    KGMergeResult,
    KGQueryResult,
    KGRelation,
    KnowledgeGraphCapabilities,
    RelationType,
)
from cemaf.knowledge.protocols import (
    BranchingKnowledgeGraph,
    KnowledgeGraph,
    KnowledgeGraphCapabilitiesProvider,
)

__all__ = [
    # Enums
    "EntityType",
    "InvalidationKind",
    "RelationType",
    # Data models
    "KGBranchDiff",
    "KGBranchRef",
    "KGEntity",
    "KGInvalidationEvent",
    "KGMergeResult",
    "KGQueryResult",
    "KGRelation",
    "KnowledgeGraphCapabilities",
    "SpokeCacheConfig",
    "SpokeStats",
    # Protocol
    "BranchingKnowledgeGraph",
    "KnowledgeGraph",
    "KnowledgeGraphCapabilitiesProvider",
    # Implementations
    "HubKnowledgeGraph",
    "LocalSpokeCache",
    "MemoryBackedKnowledgeGraph",
    "SpokeReadHubWriteKG",
    # Factories
    "create_hub_spoke_kg",
    "create_knowledge_graph",
    "knowledge_graph_registry",
    # Constants
    "KG_INVALIDATION_EVENT_TYPE",
]
