"""Knowledge graph data models — entities, relations, and query results."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from cemaf.core.types import JSON
from cemaf.core.utils import utc_now


class EntityType(StrEnum):
    """Classification of knowledge graph entities."""

    AGENT = "agent"
    TOOL = "tool"
    DAG = "dag"
    RUN = "run"
    MODULE = "module"
    PROTOCOL = "protocol"
    SKILL = "skill"


class RelationType(StrEnum):
    """Classification of knowledge graph relations."""

    USES = "uses"
    PRODUCES = "produces"
    DEPENDS_ON = "depends_on"
    EVALUATED_BY = "evaluated_by"
    EXTRACTED_FROM = "extracted_from"
    CONTAINS = "contains"
    IMPLEMENTS = "implements"


@dataclass(frozen=True, slots=True)
class KGEntity:
    """An entity node in the knowledge graph."""

    id: str
    type: EntityType
    name: str
    description: str = ""
    properties: JSON = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> JSON:
        """Serialize entity to JSON-compatible dict."""
        return {
            "id": self.id,
            "type": self.type.value,
            "name": self.name,
            "description": self.description,
            "properties": dict(self.properties),
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class KGRelation:
    """A directed relation between two entities."""

    source_id: str
    target_id: str
    type: RelationType
    properties: JSON = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> JSON:
        """Serialize relation to JSON-compatible dict."""
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "type": self.type.value,
            "properties": dict(self.properties),
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class KGQueryResult:
    """Result of a knowledge graph query."""

    entities: tuple[KGEntity, ...] = field(default_factory=tuple)
    relations: tuple[KGRelation, ...] = field(default_factory=tuple)
    metadata: JSON = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        """Whether the result contains no entities or relations."""
        return len(self.entities) == 0 and len(self.relations) == 0
