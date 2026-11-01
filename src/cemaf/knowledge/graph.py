"""Knowledge graph backed by CEMAF's MemoryManager."""

from __future__ import annotations

from datetime import datetime

from cemaf.context.patch import SecurityLevel
from cemaf.core.enums import MemoryScope
from cemaf.core.types import JSON
from cemaf.knowledge.models import (
    EntityType,
    KGEntity,
    KGQueryResult,
    KGRelation,
    RelationType,
)
from cemaf.memory.base import MemoryItem
from cemaf.memory.manager import MemoryManager
from cemaf.memory.semantic import MemoryQuery


class MemoryBackedKnowledgeGraph:
    """Knowledge graph that stores entities and relations as MemoryItems."""

    _SCOPE = MemoryScope.PROJECT
    _ENTITY_PREFIX = "kg:entity:"
    _RELATION_PREFIX = "kg:rel:"
    _INDEX_PREFIX = "kg:index:"

    def __init__(self, memory_manager: MemoryManager, *, clearance: SecurityLevel) -> None:
        self._memory = memory_manager
        self._clearance = clearance

    @property
    def clearance(self) -> SecurityLevel:
        """Highest level this graph reads or overwrites."""
        return self._clearance

    def _admits(self, item: MemoryItem) -> bool:
        """True when this reader's clearance covers the stored item."""
        return item.security_level.rank <= self._clearance.rank

    async def _refuse_overwrite_above_clearance(self, *, key: str) -> None:
        """Raise if key already holds an item this graph's clearance does not cover."""
        existing = await self._memory.recall_by_key(scope=self._SCOPE, key=key)
        if existing is not None and not self._admits(existing):
            raise PermissionError(f"Cannot overwrite {key}: stored above this graph's clearance")

    async def add_entity(self, entity: KGEntity) -> None:
        """Store entity as a MemoryItem with embedding text."""
        await self._refuse_overwrite_above_clearance(key=f"{self._ENTITY_PREFIX}{entity.id}")
        await self._memory.remember(
            scope=self._SCOPE,
            key=f"{self._ENTITY_PREFIX}{entity.id}",
            value=entity.to_dict(),
            content_for_embedding=f"{entity.name} {entity.description}",
            security_level=entity.security_level,
        )

    async def add_relation(self, relation: KGRelation) -> None:
        """Store relation and update both entities' relation indexes."""
        rel_key = f"{self._RELATION_PREFIX}{relation.source_id}:{relation.type.value}:{relation.target_id}"
        await self._refuse_overwrite_above_clearance(key=rel_key)
        await self._memory.remember(
            scope=self._SCOPE,
            key=rel_key,
            value=relation.to_dict(),
            security_level=relation.security_level,
        )
        await self._update_index(
            entity_id=relation.source_id, relation_key=rel_key, security_level=relation.security_level
        )
        await self._update_index(
            entity_id=relation.target_id, relation_key=rel_key, security_level=relation.security_level
        )

    async def get_entity(self, entity_id: str) -> KGEntity | None:
        """Retrieve entity by ID from memory."""
        item = await self._memory.recall_by_key(
            scope=self._SCOPE,
            key=f"{self._ENTITY_PREFIX}{entity_id}",
        )
        if item is None or not self._admits(item):
            return None
        return self._entity_from_dict(data=item.value)

    async def query_neighbors(
        self,
        entity_id: str,
        relation_type: RelationType | None = None,
        depth: int = 1,
    ) -> KGQueryResult:
        """Find connected entities via the relation index."""
        visited_entities: set[str] = set()
        all_entities: list[KGEntity] = []
        all_relations: list[KGRelation] = []
        if await self.get_entity(entity_id=entity_id) is None:
            return KGQueryResult(metadata={"root_entity_id": entity_id, "depth": depth})

        await self._collect_neighbors(
            entity_id=entity_id,
            relation_type=relation_type,
            depth=depth,
            visited=visited_entities,
            entities_out=all_entities,
            relations_out=all_relations,
        )

        return KGQueryResult(
            entities=tuple(all_entities),
            relations=tuple(all_relations),
            metadata={"root_entity_id": entity_id, "depth": depth},
        )

    async def search(
        self,
        query: str,
        entity_type: EntityType | None = None,
        limit: int = 10,
    ) -> tuple[KGEntity, ...]:
        """Semantic search for entities via MemoryManager.recall()."""
        results = await self._memory.recall(
            MemoryQuery(
                text=query,
                scope=self._SCOPE,
                limit=limit * 2,
                max_security_level=self._clearance,
            )
        )
        entities: list[KGEntity] = []
        for result in results:
            if not result.item.key.startswith(self._ENTITY_PREFIX) or not self._admits(result.item):
                continue
            entity = self._entity_from_dict(data=result.item.value)
            if entity_type is not None and entity.type != entity_type:
                continue
            entities.append(entity)
            if len(entities) >= limit:
                break
        return tuple(entities)

    async def remove_entity(self, entity_id: str) -> bool:
        """Remove entity, its relations, and clean up indexes."""
        entity_key = f"{self._ENTITY_PREFIX}{entity_id}"
        existing = await self._memory.recall_by_key(
            scope=self._SCOPE,
            key=entity_key,
        )
        if existing is None or not self._admits(existing):
            return False

        # Get the entity's relation index and remove all listed relations.
        index_key = f"{self._INDEX_PREFIX}{entity_id}"
        index_item = await self._memory.recall_by_key(
            scope=self._SCOPE,
            key=index_key,
        )
        if index_item is not None:
            relation_keys: list[str] = index_item.value.get("relation_keys", [])
            relation_items = [
                await self._memory.recall_by_key(scope=self._SCOPE, key=rel_key) for rel_key in relation_keys
            ]
            if not self._admits(index_item) or any(
                item is not None and not self._admits(item) for item in relation_items
            ):
                raise PermissionError(f"Cannot remove {entity_id}: it has relations above clearance")
            for rel_key in relation_keys:
                # Load relation to find the other entity and clean its index.
                rel_item = await self._memory.recall_by_key(
                    scope=self._SCOPE,
                    key=rel_key,
                )
                if rel_item is not None:
                    relation = self._relation_from_dict(data=rel_item.value)
                    other_id = relation.target_id if relation.source_id == entity_id else relation.source_id
                    await self._remove_from_index(
                        entity_id=other_id,
                        relation_key=rel_key,
                    )
                await self._memory.forget(scope=self._SCOPE, key=rel_key)

            # Remove the entity's own index.
            await self._memory.forget(scope=self._SCOPE, key=index_key)

        # Remove the entity itself.
        await self._memory.forget(scope=self._SCOPE, key=entity_key)
        return True

    # -- Private helpers -------------------------------------------------------

    async def _collect_neighbors(
        self,
        *,
        entity_id: str,
        relation_type: RelationType | None,
        depth: int,
        visited: set[str],
        entities_out: list[KGEntity],
        relations_out: list[KGRelation],
    ) -> None:
        """Recursively collect neighbor entities and relations."""
        if depth <= 0:
            return
        visited.add(entity_id)

        index_item = await self._memory.recall_by_key(
            scope=self._SCOPE,
            key=f"{self._INDEX_PREFIX}{entity_id}",
        )
        if index_item is None:
            return

        relation_keys: list[str] = index_item.value.get("relation_keys", [])
        for rel_key in relation_keys:
            rel_item = await self._memory.recall_by_key(
                scope=self._SCOPE,
                key=rel_key,
            )
            if rel_item is None or not self._admits(rel_item):
                continue

            relation = self._relation_from_dict(data=rel_item.value)
            if relation_type is not None and relation.type != relation_type:
                continue

            # A relation is only visible when the entity on its other side is too.
            neighbor_id = relation.target_id if relation.source_id == entity_id else relation.source_id
            neighbor = await self.get_entity(entity_id=neighbor_id)
            if neighbor is None:
                continue
            relations_out.append(relation)
            if neighbor_id in visited:
                continue
            entities_out.append(neighbor)

            # Recurse for deeper traversal.
            await self._collect_neighbors(
                entity_id=neighbor_id,
                relation_type=relation_type,
                depth=depth - 1,
                visited=visited,
                entities_out=entities_out,
                relations_out=relations_out,
            )

    async def _update_index(
        self, *, entity_id: str, relation_key: str, security_level: SecurityLevel
    ) -> None:
        """Add a relation key to an entity's index; the index takes the highest level it lists."""
        index_key = f"{self._INDEX_PREFIX}{entity_id}"
        existing = await self._memory.recall_by_key(
            scope=self._SCOPE,
            key=index_key,
        )
        if existing is not None:
            keys = list(existing.value.get("relation_keys", []))
            if relation_key not in keys:
                keys.append(relation_key)
            await self._memory.remember(
                scope=self._SCOPE,
                key=index_key,
                value={"relation_keys": keys},
                security_level=max(existing.security_level, security_level, key=lambda level: level.rank),
            )
        else:
            await self._memory.remember(
                scope=self._SCOPE,
                key=index_key,
                value={"relation_keys": [relation_key]},
                security_level=security_level,
            )

    async def _remove_from_index(
        self,
        *,
        entity_id: str,
        relation_key: str,
    ) -> None:
        """Remove a relation key from an entity's relation index."""
        index_key = f"{self._INDEX_PREFIX}{entity_id}"
        index_item = await self._memory.recall_by_key(
            scope=self._SCOPE,
            key=index_key,
        )
        if index_item is None:
            return
        keys = [k for k in index_item.value.get("relation_keys", []) if k != relation_key]
        if keys:
            await self._memory.remember(
                scope=self._SCOPE,
                key=index_key,
                value={"relation_keys": keys},
                security_level=index_item.security_level,
            )
        else:
            await self._memory.forget(scope=self._SCOPE, key=index_key)

    @staticmethod
    def _entity_from_dict(data: JSON) -> KGEntity:
        """Reconstruct KGEntity from stored dict."""
        return KGEntity(
            id=data["id"],
            type=EntityType(data["type"]),
            name=data["name"],
            description=data.get("description", ""),
            properties=data.get("properties", {}),
            created_at=datetime.fromisoformat(data["created_at"]),
            security_level=SecurityLevel(data.get("security_level", SecurityLevel.INTERNAL.value)),
        )

    @staticmethod
    def _relation_from_dict(data: JSON) -> KGRelation:
        """Reconstruct KGRelation from stored dict."""
        return KGRelation(
            source_id=data["source_id"],
            target_id=data["target_id"],
            type=RelationType(data["type"]),
            properties=data.get("properties", {}),
            created_at=datetime.fromisoformat(data["created_at"]),
            security_level=SecurityLevel(data.get("security_level", SecurityLevel.INTERNAL.value)),
        )
