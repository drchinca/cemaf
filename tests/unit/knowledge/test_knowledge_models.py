"""Contract and unit tests for knowledge graph models and protocol."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

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


class TestOptionalKnowledgeGraphProtocols:
    """Verify optional graph-backend protocols remain additive."""

    def test_branching_protocol_runtime_checkable(self) -> None:
        class BranchingGraph:
            async def list_branches(self) -> tuple[KGBranchRef, ...]: ...

            async def create_branch(
                self,
                name: str,
                *,
                from_branch: str = "main",
            ) -> KGBranchRef: ...

            async def diff_branch(
                self,
                name: str,
                *,
                against: str = "main",
            ) -> KGBranchDiff: ...

            async def merge_branch(
                self,
                name: str,
                *,
                into: str = "main",
            ) -> KGMergeResult: ...

        assert isinstance(BranchingGraph(), BranchingKnowledgeGraph)

    def test_simple_knowledge_graph_does_not_implicitly_branch(self) -> None:
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

        graph = FakeGraph()
        assert isinstance(graph, KnowledgeGraph)
        assert not isinstance(graph, BranchingKnowledgeGraph)

    def test_capabilities_provider_runtime_checkable(self) -> None:
        class CapableGraph:
            @property
            def capabilities(self) -> KnowledgeGraphCapabilities:
                return KnowledgeGraphCapabilities(branching=True)

        assert isinstance(CapableGraph(), KnowledgeGraphCapabilitiesProvider)


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


class TestKGBranchModels:
    """Contract tests for optional branch/version adapter models."""

    def test_branch_ref_defaults(self) -> None:
        ref = KGBranchRef(name="agent/task-1")
        assert ref.name == "agent/task-1"
        assert ref.base_branch is None
        assert ref.metadata == {}

    def test_branch_diff_empty(self) -> None:
        diff = KGBranchDiff(source_branch="agent/task-1", target_branch="main")
        assert diff.empty is True

    def test_branch_diff_not_empty_with_entity_change(self) -> None:
        diff = KGBranchDiff(
            source_branch="agent/task-1",
            target_branch="main",
            added_entities=("entity-1",),
        )
        assert diff.empty is False

    def test_merge_result_clean(self) -> None:
        result = KGMergeResult(source_branch="agent/task-1", target_branch="main", merged=True)
        assert result.clean is True

    def test_merge_result_with_conflicts_is_not_clean(self) -> None:
        result = KGMergeResult(
            source_branch="agent/task-1",
            target_branch="main",
            merged=False,
            conflicts=("entity-1",),
        )
        assert result.clean is False

    def test_capabilities_defaults(self) -> None:
        capabilities = KnowledgeGraphCapabilities()
        assert capabilities.branching is False
        assert capabilities.snapshots is False
        assert capabilities.hybrid_retrieval is False
        assert capabilities.server_side_policy is False
        assert capabilities.metadata == {}
