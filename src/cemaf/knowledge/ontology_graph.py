"""A knowledge graph that checks writes against an ontology and records violations (SPEC-27)."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import replace
from typing import Final

from cemaf.events.protocols import Event, EventBus, EventType
from cemaf.knowledge.models import KGEntity, KGQueryResult, KGRelation, KnowledgeGraphCapabilities
from cemaf.knowledge.ontology import Ontology, OntologyViolation
from cemaf.knowledge.protocols import KnowledgeGraph, KnowledgeGraphCapabilitiesProvider

_log = logging.getLogger(__name__)

DEFAULT_RECENT_VIOLATION_LIMIT: Final = 1_000
VIOLATION_EVENT_SOURCE: Final = "knowledge.ontology"


class OntologyKnowledgeGraph:
    """Wraps a KnowledgeGraph: every write is validated, then written whatever its violations."""

    def __init__(
        self,
        *,
        graph: KnowledgeGraph,
        ontology: Ontology,
        event_bus: EventBus | None = None,
        recent_violation_limit: int = DEFAULT_RECENT_VIOLATION_LIMIT,
    ) -> None:
        if recent_violation_limit < 1:
            raise ValueError("recent_violation_limit must be at least 1")
        self._graph = graph
        self._ontology = ontology
        self._event_bus = event_bus
        self._recent: deque[OntologyViolation] = deque(maxlen=recent_violation_limit)

    @property
    def ontology(self) -> Ontology:
        """The ontology writes are checked against."""
        return self._ontology

    def recent_violations(self) -> tuple[OntologyViolation, ...]:
        """The most recent violations, oldest first; events carry every one."""
        return tuple(self._recent)

    @property
    def capabilities(self) -> KnowledgeGraphCapabilities:
        """The wrapped graph's capabilities, minus branching, which the wrapper does not expose."""
        if isinstance(self._graph, KnowledgeGraphCapabilitiesProvider):
            return replace(self._graph.capabilities, branching=False)
        return KnowledgeGraphCapabilities()

    async def add_entity(self, entity: KGEntity) -> None:
        """Validate the entity, record any violations, then write it."""
        await self._record(violations=self._ontology.validate_entity(entity=entity))
        await self._graph.add_entity(entity=entity)

    async def add_relation(self, relation: KGRelation) -> None:
        """Validate the relation (endpoints, classes, cardinality), record violations, then write it."""
        source = await self._graph.get_entity(entity_id=relation.source_id)
        target = await self._graph.get_entity(entity_id=relation.target_id)
        existing = await self._graph.relations_from(entity_id=relation.source_id, relation_type=relation.type)
        others = [rel for rel in existing if rel.target_id != relation.target_id]
        violations = self._ontology.validate_relation(
            relation=relation,
            source=source,
            target=target,
            existing_from_source=len(others),
        )
        await self._record(violations=violations)
        await self._graph.add_relation(relation=relation)

    async def entities_of_class(
        self, *, class_name: str, include_subclasses: bool = True
    ) -> tuple[KGEntity, ...]:
        """Every visible entity of the class and, by default, of each class below it."""
        class_names = [class_name]
        if include_subclasses:
            class_names.extend(self._ontology.descendants(class_name=class_name))
        entities: list[KGEntity] = []
        for name in class_names:
            entities.extend(await self._graph.entities_of_type(entity_type=name))
        return tuple(sorted(entities, key=lambda entity: entity.id))

    async def related(self, *, entity_id: str, relation: str) -> tuple[KGEntity, ...]:
        """The visible targets of entity_id's outgoing relations of this type, one hop."""
        targets: list[KGEntity] = []
        for rel in await self._graph.relations_from(entity_id=entity_id, relation_type=relation):
            target = await self._graph.get_entity(entity_id=rel.target_id)
            if target is not None:
                targets.append(target)
        return tuple(targets)

    async def get_entity(self, entity_id: str) -> KGEntity | None:
        """Read through to the wrapped graph."""
        return await self._graph.get_entity(entity_id=entity_id)

    async def query_neighbors(
        self,
        entity_id: str,
        relation_type: str | None = None,
        depth: int = 1,
    ) -> KGQueryResult:
        """Read through to the wrapped graph."""
        return await self._graph.query_neighbors(
            entity_id=entity_id, relation_type=relation_type, depth=depth
        )

    async def search(
        self,
        query: str,
        entity_type: str | None = None,
        limit: int = 10,
    ) -> tuple[KGEntity, ...]:
        """Read through to the wrapped graph."""
        return await self._graph.search(query=query, entity_type=entity_type, limit=limit)

    async def entities_of_type(self, *, entity_type: str) -> tuple[KGEntity, ...]:
        """Read through to the wrapped graph."""
        return await self._graph.entities_of_type(entity_type=entity_type)

    async def relations_from(
        self, *, entity_id: str, relation_type: str | None = None
    ) -> tuple[KGRelation, ...]:
        """Read through to the wrapped graph."""
        return await self._graph.relations_from(entity_id=entity_id, relation_type=relation_type)

    async def remove_entity(self, entity_id: str) -> bool:
        """Removal has no ontology rule to break; delegate."""
        return await self._graph.remove_entity(entity_id=entity_id)

    async def _record(self, *, violations: tuple[OntologyViolation, ...]) -> None:
        for violation in violations:
            self._recent.append(violation)
            payload = {
                "ontology": self._ontology.name,
                "version": self._ontology.version,
                "kind": str(violation.kind),
                "subject_id": violation.subject_id,
                "message": violation.message,
            }
            _log.info("ontology.violation", extra={"ontology_violation": payload})
            if self._event_bus is not None:
                await self._event_bus.publish(
                    Event.create(
                        type=EventType.ONTOLOGY_VIOLATION, payload=payload, source=VIOLATION_EVENT_SOURCE
                    )
                )
