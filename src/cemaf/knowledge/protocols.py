"""Knowledge graph protocol — abstract interface for graph backends."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cemaf.knowledge.models import (
    EntityType,
    KGEntity,
    KGQueryResult,
    KGRelation,
    RelationType,
)


@runtime_checkable
class KnowledgeGraph(Protocol):
    """Protocol for knowledge graph implementations."""

    async def add_entity(self, entity: KGEntity) -> None:
        """Store an entity in the graph."""
        ...

    async def add_relation(self, relation: KGRelation) -> None:
        """Store a relation between two entities."""
        ...

    async def get_entity(self, entity_id: str) -> KGEntity | None:
        """Retrieve an entity by ID, or None if not found."""
        ...

    async def query_neighbors(
        self,
        entity_id: str,
        relation_type: RelationType | None = None,
        depth: int = 1,
    ) -> KGQueryResult:
        """Find entities connected to the given entity."""
        ...

    async def search(
        self,
        query: str,
        entity_type: EntityType | None = None,
        limit: int = 10,
    ) -> tuple[KGEntity, ...]:
        """Search entities by text query with optional type filter."""
        ...

    async def remove_entity(self, entity_id: str) -> bool:
        """Remove an entity and its relations, returning True if it existed."""
        ...
