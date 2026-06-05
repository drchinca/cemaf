"""Knowledge graph module — entity/relation modeling and graph queries."""

from cemaf.knowledge.factories import create_knowledge_graph
from cemaf.knowledge.graph import MemoryBackedKnowledgeGraph
from cemaf.knowledge.hub_spoke import (
    KG_INVALIDATION_EVENT_TYPE,
    HubKnowledgeGraph,
    InvalidationKind,
    KGInvalidationEvent,
    LocalSpokeCache,
    SpokeCacheConfig,
    SpokeStats,
    create_hub_spoke_kg,
)
from cemaf.knowledge.models import (
    EntityType,
    KGEntity,
    KGQueryResult,
    KGRelation,
    RelationType,
)
from cemaf.knowledge.protocols import KnowledgeGraph

__all__ = [
    # Enums
    "EntityType",
    "InvalidationKind",
    "RelationType",
    # Data models
    "KGEntity",
    "KGInvalidationEvent",
    "KGQueryResult",
    "KGRelation",
    "SpokeCacheConfig",
    "SpokeStats",
    # Protocol
    "KnowledgeGraph",
    # Implementations
    "HubKnowledgeGraph",
    "LocalSpokeCache",
    "MemoryBackedKnowledgeGraph",
    # Factories
    "create_hub_spoke_kg",
    "create_knowledge_graph",
    # Constants
    "KG_INVALIDATION_EVENT_TYPE",
]
