"""Contract and unit tests for knowledge graph models and protocol."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from cemaf.knowledge.models import (
    EntityType,
    KGEntity,
    KGQueryResult,
    KGRelation,
    RelationType,
)
from cemaf.knowledge.protocols import KnowledgeGraph


class TestKnowledgeGraphProtocol:
    """Verify KnowledgeGraph is runtime-checkable."""

    def test_runtime_checkable(self) -> None:
        """Protocol can be used with isinstance checks."""

        class FakeGraph:
            async def add_entity(self, entity: KGEntity) -> None: ...
            async def add_relation(self, relation: KGRelation) -> None: ...
            async def get_entity(self, entity_id: str) -> KGEntity | None: ...
            async def query_neighbors(
                self,
                entity_id: str,
                relation_type: RelationType | None = None,
                depth: int = 1,
            ) -> KGQueryResult: ...
            async def search(
                self,
                query: str,
                entity_type: EntityType | None = None,
                limit: int = 10,
            ) -> tuple[KGEntity, ...]: ...
            async def remove_entity(self, entity_id: str) -> bool: ...

        assert isinstance(FakeGraph(), KnowledgeGraph)

    def test_non_implementor_fails_check(self) -> None:
        """Object missing methods does not satisfy protocol."""

        class NotAGraph:
            pass

        assert not isinstance(NotAGraph(), KnowledgeGraph)


class TestEntityType:
    """Verify EntityType enum values."""

    def test_enum_values(self) -> None:
        assert EntityType.AGENT.value == "agent"
        assert EntityType.TOOL.value == "tool"
        assert EntityType.DAG.value == "dag"
        assert EntityType.RUN.value == "run"
        assert EntityType.MODULE.value == "module"
        assert EntityType.PROTOCOL.value == "protocol"
        assert EntityType.SKILL.value == "skill"

    def test_member_count(self) -> None:
        assert len(EntityType) == 7


class TestRelationType:
    """Verify RelationType enum values."""

    def test_enum_values(self) -> None:
        assert RelationType.USES.value == "uses"
        assert RelationType.PRODUCES.value == "produces"
        assert RelationType.DEPENDS_ON.value == "depends_on"
        assert RelationType.EVALUATED_BY.value == "evaluated_by"
        assert RelationType.EXTRACTED_FROM.value == "extracted_from"
        assert RelationType.CONTAINS.value == "contains"
        assert RelationType.IMPLEMENTS.value == "implements"

    def test_member_count(self) -> None:
        assert len(RelationType) == 7


class TestKGEntity:
    """Contract tests for KGEntity frozen dataclass."""

    def test_frozen(self) -> None:
        entity = KGEntity(
            id="e1",
            type=EntityType.AGENT,
            name="ResearchAgent",
        )
        with pytest.raises(FrozenInstanceError):
            entity.name = "Other"  # type: ignore[misc]

    def test_defaults(self) -> None:
        entity = KGEntity(
            id="e1",
            type=EntityType.TOOL,
            name="SearchTool",
        )
        assert entity.description == ""
        assert entity.properties == {}
        assert entity.created_at is not None

    def test_to_dict_round_trip(self) -> None:
        entity = KGEntity(
            id="e1",
            type=EntityType.MODULE,
            name="memory",
            description="Memory subsystem",
            properties={"version": "2.0"},
        )
        d = entity.to_dict()
        assert d["id"] == "e1"
        assert d["type"] == "module"
        assert d["name"] == "memory"
        assert d["description"] == "Memory subsystem"
        assert d["properties"] == {"version": "2.0"}
        assert isinstance(d["created_at"], str)

    def test_to_dict_contains_all_fields(self) -> None:
        entity = KGEntity(
            id="e2",
            type=EntityType.PROTOCOL,
            name="KnowledgeGraph",
        )
        d = entity.to_dict()
        expected_keys = {"id", "type", "name", "description", "properties", "created_at"}
        assert set(d.keys()) == expected_keys


class TestKGRelation:
    """Contract tests for KGRelation frozen dataclass."""

    def test_frozen(self) -> None:
        relation = KGRelation(
            source_id="e1",
            target_id="e2",
            type=RelationType.USES,
        )
        with pytest.raises(FrozenInstanceError):
            relation.source_id = "e3"  # type: ignore[misc]

    def test_defaults(self) -> None:
        relation = KGRelation(
            source_id="e1",
            target_id="e2",
            type=RelationType.DEPENDS_ON,
        )
        assert relation.properties == {}
        assert relation.created_at is not None

    def test_to_dict_round_trip(self) -> None:
        relation = KGRelation(
            source_id="a1",
            target_id="a2",
            type=RelationType.PRODUCES,
            properties={"confidence": 0.9},
        )
        d = relation.to_dict()
        assert d["source_id"] == "a1"
        assert d["target_id"] == "a2"
        assert d["type"] == "produces"
        assert d["properties"] == {"confidence": 0.9}
        assert isinstance(d["created_at"], str)

    def test_to_dict_contains_all_fields(self) -> None:
        relation = KGRelation(
            source_id="x",
            target_id="y",
            type=RelationType.IMPLEMENTS,
        )
        d = relation.to_dict()
        expected_keys = {"source_id", "target_id", "type", "properties", "created_at"}
        assert set(d.keys()) == expected_keys


class TestKGQueryResult:
    """Contract tests for KGQueryResult frozen dataclass."""

    def test_frozen(self) -> None:
        result = KGQueryResult()
        with pytest.raises(FrozenInstanceError):
            result.metadata = {"changed": True}  # type: ignore[misc]

    def test_empty_when_no_entities_or_relations(self) -> None:
        result = KGQueryResult()
        assert result.empty is True

    def test_not_empty_with_entities(self) -> None:
        entity = KGEntity(
            id="e1",
            type=EntityType.AGENT,
            name="TestAgent",
        )
        result = KGQueryResult(entities=(entity,))
        assert result.empty is False

    def test_not_empty_with_relations(self) -> None:
        relation = KGRelation(
            source_id="e1",
            target_id="e2",
            type=RelationType.USES,
        )
        result = KGQueryResult(relations=(relation,))
        assert result.empty is False

    def test_defaults(self) -> None:
        result = KGQueryResult()
        assert result.entities == ()
        assert result.relations == ()
        assert result.metadata == {}
