"""Knowledge graph module — entity/relation modeling and graph queries."""

from cemaf.knowledge.factories import create_knowledge_graph
from cemaf.knowledge.graph import MemoryBackedKnowledgeGraph
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
    "RelationType",
    # Data models
    "KGEntity",
    "KGRelation",
    "KGQueryResult",
    # Protocol
    "KnowledgeGraph",
    # Implementation
    "MemoryBackedKnowledgeGraph",
    # Factory
    "create_knowledge_graph",
]
