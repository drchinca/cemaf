"""Knowledge graph protocol — abstract interface for graph backends."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cemaf.knowledge.models import (
    KGBranchDiff,
    KGBranchRef,
    KGEntity,
    KGMergeResult,
    KGQueryResult,
    KGRelation,
    KnowledgeGraphCapabilities,
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
        relation_type: str | None = None,
        depth: int = 1,
    ) -> KGQueryResult:
        """Find entities connected to the given entity."""
        ...

    async def search(
        self,
        query: str,
        entity_type: str | None = None,
        limit: int = 10,
    ) -> tuple[KGEntity, ...]:
        """Search entities by text query with optional type filter."""
        ...

    async def entities_of_type(self, *, entity_type: str) -> tuple[KGEntity, ...]:
        """Every visible entity of exactly this type; no limit or ranking (SPEC-27)."""
        ...

    async def relations_from(
        self, *, entity_id: str, relation_type: str | None = None
    ) -> tuple[KGRelation, ...]:
        """Visible relations whose source is entity_id, whatever the target's visibility (SPEC-27)."""
        ...

    async def remove_entity(self, entity_id: str) -> bool:
        """Remove an entity and its relations, returning True if it existed."""
        ...


@runtime_checkable
class KnowledgeGraphCapabilitiesProvider(Protocol):
    """Optional protocol for adapters that can describe backend capabilities."""

    @property
    def capabilities(self) -> KnowledgeGraphCapabilities:
        """Describe optional capabilities without changing the core KG protocol."""
        ...


@runtime_checkable
class BranchingKnowledgeGraph(Protocol):
    """Optional protocol for backend-owned KG branch workflows.

    This is deliberately separate from `KnowledgeGraph`: most CEMAF graph
    backends should remain simple CRUD/search stores. Backends such as graph
    databases or lakehouse graph engines can additionally implement this
    protocol to support agent/task branches, review diffs, and merges.
    """

    async def list_branches(self) -> tuple[KGBranchRef, ...]:
        """List backend-visible knowledge graph branches."""
        ...

    async def create_branch(
        self,
        name: str,
        *,
        from_branch: str = "main",
    ) -> KGBranchRef:
        """Create an isolated branch from an existing branch."""
        ...

    async def diff_branch(
        self,
        name: str,
        *,
        against: str = "main",
    ) -> KGBranchDiff:
        """Return a backend-reported diff for review before merge."""
        ...

    async def merge_branch(
        self,
        name: str,
        *,
        into: str = "main",
    ) -> KGMergeResult:
        """Ask the backend to merge a branch into another branch."""
        ...
