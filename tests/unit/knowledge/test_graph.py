"""Tests for MemoryBackedKnowledgeGraph."""

from __future__ import annotations

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.core.types import JSON, Confidence
from cemaf.knowledge.factories import create_knowledge_graph
from cemaf.knowledge.graph import MemoryBackedKnowledgeGraph
from cemaf.knowledge.models import (
    EntityType,
    KGEntity,
    KGRelation,
    RelationType,
)
from cemaf.knowledge.protocols import KnowledgeGraph
from cemaf.memory.base import MemoryItem
from cemaf.memory.episodic import Episode, EpisodicEvent
from cemaf.memory.semantic import MemoryQuery, MemorySearchResult

# ---------------------------------------------------------------------------
# Fake MemoryManager
# ---------------------------------------------------------------------------


class FakeMemoryManager:
    """In-memory MemoryManager for testing — stores items in a dict."""

    def __init__(self) -> None:
        self._store: dict[str, MemoryItem] = {}

    async def remember(
        self,
        scope: MemoryScope,
        key: str,
        value: JSON,
        *,
        confidence: float = 1.0,
        content_for_embedding: str | None = None,
    ) -> MemoryItem:
        """Store item keyed by scope:key."""
        item = MemoryItem(
            scope=scope,
            key=key,
            value=value,
            confidence=Confidence(confidence),
        )
        self._store[f"{scope.value}:{key}"] = item
        return item

    async def recall(self, query: MemoryQuery) -> tuple[MemorySearchResult, ...]:
        """Simple text search across stored items."""
        results: list[MemorySearchResult] = []
        search_text = (query.text or "").lower()
        for item in self._store.values():
            if query.scope is not None and item.scope != query.scope:
                continue
            text_repr = f"{item.key} {str(item.value)}".lower()
            if search_text and search_text not in text_repr:
                continue
            results.append(
                MemorySearchResult(
                    item=item,
                    similarity=0.9,
                    combined_score=0.9,
                    rank=len(results),
                )
            )
            if len(results) >= query.limit:
                break
        return tuple(results)

    async def recall_by_key(
        self,
        scope: MemoryScope,
        key: str,
    ) -> MemoryItem | None:
        """Direct key lookup."""
        return self._store.get(f"{scope.value}:{key}")

    async def forget(self, scope: MemoryScope, key: str) -> bool:
        """Remove an item."""
        full_key = f"{scope.value}:{key}"
        if full_key in self._store:
            del self._store[full_key]
            return True
        return False

    # -- Episodic stubs (not used by KG, but required by protocol) ----------

    async def start_episode(self, session_id: str) -> Episode:
        raise NotImplementedError

    async def record_event(self, episode_id: str, event: EpisodicEvent) -> None:
        raise NotImplementedError

    async def end_episode(self, episode_id: str) -> Episode:
        raise NotImplementedError

    async def get_recent_history(
        self,
        session_id: str,
        *,
        limit: int = 20,
    ) -> tuple[EpisodicEvent, ...]:
        raise NotImplementedError

    async def cleanup(self) -> int:
        return 0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_memory() -> FakeMemoryManager:
    return FakeMemoryManager()


@pytest.fixture()
def graph(fake_memory: FakeMemoryManager) -> MemoryBackedKnowledgeGraph:
    return MemoryBackedKnowledgeGraph(memory_manager=fake_memory)


def _make_entity(
    entity_id: str = "ent-1",
    entity_type: EntityType = EntityType.AGENT,
    name: str = "TestAgent",
    description: str = "A test agent",
) -> KGEntity:
    return KGEntity(
        id=entity_id,
        type=entity_type,
        name=name,
        description=description,
    )


def _make_relation(
    source_id: str = "ent-1",
    target_id: str = "ent-2",
    rel_type: RelationType = RelationType.USES,
) -> KGRelation:
    return KGRelation(
        source_id=source_id,
        target_id=target_id,
        type=rel_type,
    )


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_satisfies_knowledge_graph_protocol(self) -> None:
        """MemoryBackedKnowledgeGraph is a structural KnowledgeGraph."""
        assert isinstance(
            MemoryBackedKnowledgeGraph(memory_manager=FakeMemoryManager()),
            KnowledgeGraph,
        )


# ---------------------------------------------------------------------------
# add_entity / get_entity
# ---------------------------------------------------------------------------


class TestAddAndGetEntity:
    @pytest.mark.asyncio()
    async def test_add_then_get(self, graph: MemoryBackedKnowledgeGraph) -> None:
        """Round-trip: add entity then retrieve it."""
        entity = _make_entity()
        await graph.add_entity(entity=entity)

        retrieved = await graph.get_entity(entity_id="ent-1")
        assert retrieved is not None
        assert retrieved.id == entity.id
        assert retrieved.type == entity.type
        assert retrieved.name == entity.name
        assert retrieved.description == entity.description

    @pytest.mark.asyncio()
    async def test_get_missing_entity_returns_none(self, graph: MemoryBackedKnowledgeGraph) -> None:
        """get_entity returns None for nonexistent ID."""
        result = await graph.get_entity(entity_id="does-not-exist")
        assert result is None

    @pytest.mark.asyncio()
    async def test_add_preserves_properties(self, graph: MemoryBackedKnowledgeGraph) -> None:
        """Entity properties survive the round-trip."""
        entity = KGEntity(
            id="prop-1",
            type=EntityType.TOOL,
            name="MyTool",
            description="tool with props",
            properties={"version": "2.0", "tags": ["fast"]},
        )
        await graph.add_entity(entity=entity)
        retrieved = await graph.get_entity(entity_id="prop-1")
        assert retrieved is not None
        assert retrieved.properties == {"version": "2.0", "tags": ["fast"]}


# ---------------------------------------------------------------------------
# add_relation + index
# ---------------------------------------------------------------------------


class TestAddRelation:
    @pytest.mark.asyncio()
    async def test_add_relation_stores_and_indexes(
        self, graph: MemoryBackedKnowledgeGraph, fake_memory: FakeMemoryManager
    ) -> None:
        """Adding a relation stores the relation and updates both entity indexes."""
        await graph.add_entity(entity=_make_entity(entity_id="a"))
        await graph.add_entity(entity=_make_entity(entity_id="b", name="AgentB"))
        relation = _make_relation(source_id="a", target_id="b")

        await graph.add_relation(relation=relation)

        # Relation stored
        rel_key = "kg:rel:a:uses:b"
        rel_item = await fake_memory.recall_by_key(scope=MemoryScope.PROJECT, key=rel_key)
        assert rel_item is not None
        assert rel_item.value["source_id"] == "a"

        # Source index updated
        src_idx = await fake_memory.recall_by_key(scope=MemoryScope.PROJECT, key="kg:index:a")
        assert src_idx is not None
        assert rel_key in src_idx.value["relation_keys"]

        # Target index updated
        tgt_idx = await fake_memory.recall_by_key(scope=MemoryScope.PROJECT, key="kg:index:b")
        assert tgt_idx is not None
        assert rel_key in tgt_idx.value["relation_keys"]

    @pytest.mark.asyncio()
    async def test_duplicate_relation_key_not_appended(
        self, graph: MemoryBackedKnowledgeGraph, fake_memory: FakeMemoryManager
    ) -> None:
        """Adding the same relation twice does not duplicate the index entry."""
        await graph.add_entity(entity=_make_entity(entity_id="x"))
        await graph.add_entity(entity=_make_entity(entity_id="y", name="Y"))
        relation = _make_relation(source_id="x", target_id="y")

        await graph.add_relation(relation=relation)
        await graph.add_relation(relation=relation)

        idx = await fake_memory.recall_by_key(scope=MemoryScope.PROJECT, key="kg:index:x")
        assert idx is not None
        keys = idx.value["relation_keys"]
        assert len(keys) == len(set(keys))


# ---------------------------------------------------------------------------
# query_neighbors
# ---------------------------------------------------------------------------


class TestQueryNeighbors:
    @pytest.mark.asyncio()
    async def test_depth_one(self, graph: MemoryBackedKnowledgeGraph) -> None:
        """query_neighbors at depth=1 returns direct neighbors."""
        agent = _make_entity(entity_id="agent-1", name="Agent1")
        tool = _make_entity(entity_id="tool-1", entity_type=EntityType.TOOL, name="Tool1")
        await graph.add_entity(entity=agent)
        await graph.add_entity(entity=tool)
        await graph.add_relation(
            relation=_make_relation(source_id="agent-1", target_id="tool-1", rel_type=RelationType.USES)
        )

        result = await graph.query_neighbors(entity_id="agent-1", depth=1)
        assert len(result.entities) == 1
        assert result.entities[0].id == "tool-1"
        assert len(result.relations) == 1
        assert result.relations[0].type == RelationType.USES

    @pytest.mark.asyncio()
    async def test_filter_by_relation_type(self, graph: MemoryBackedKnowledgeGraph) -> None:
        """query_neighbors filters relations by type."""
        await graph.add_entity(entity=_make_entity(entity_id="a"))
        await graph.add_entity(entity=_make_entity(entity_id="b", name="B"))
        await graph.add_entity(entity=_make_entity(entity_id="c", name="C"))
        await graph.add_relation(
            relation=_make_relation(source_id="a", target_id="b", rel_type=RelationType.USES)
        )
        await graph.add_relation(
            relation=_make_relation(source_id="a", target_id="c", rel_type=RelationType.DEPENDS_ON)
        )

        uses_result = await graph.query_neighbors(entity_id="a", relation_type=RelationType.USES)
        assert len(uses_result.entities) == 1
        assert uses_result.entities[0].id == "b"

        depends_result = await graph.query_neighbors(entity_id="a", relation_type=RelationType.DEPENDS_ON)
        assert len(depends_result.entities) == 1
        assert depends_result.entities[0].id == "c"

    @pytest.mark.asyncio()
    async def test_depth_two(self, graph: MemoryBackedKnowledgeGraph) -> None:
        """query_neighbors at depth=2 traverses two hops."""
        await graph.add_entity(entity=_make_entity(entity_id="a", name="A"))
        await graph.add_entity(entity=_make_entity(entity_id="b", name="B"))
        await graph.add_entity(entity=_make_entity(entity_id="c", name="C"))
        await graph.add_relation(relation=_make_relation(source_id="a", target_id="b"))
        await graph.add_relation(relation=_make_relation(source_id="b", target_id="c"))

        result = await graph.query_neighbors(entity_id="a", depth=2)
        entity_ids = {e.id for e in result.entities}
        assert "b" in entity_ids
        assert "c" in entity_ids

    @pytest.mark.asyncio()
    async def test_empty_neighbors(self, graph: MemoryBackedKnowledgeGraph) -> None:
        """query_neighbors returns empty result for entity with no relations."""
        await graph.add_entity(entity=_make_entity(entity_id="lonely"))
        result = await graph.query_neighbors(entity_id="lonely")
        assert result.empty

    @pytest.mark.asyncio()
    async def test_cycle_does_not_infinite_loop(self, graph: MemoryBackedKnowledgeGraph) -> None:
        """Cycles in the graph do not cause infinite recursion."""
        await graph.add_entity(entity=_make_entity(entity_id="x", name="X"))
        await graph.add_entity(entity=_make_entity(entity_id="y", name="Y"))
        await graph.add_relation(relation=_make_relation(source_id="x", target_id="y"))
        await graph.add_relation(relation=_make_relation(source_id="y", target_id="x"))

        result = await graph.query_neighbors(entity_id="x", depth=5)
        # Should complete without hanging; just verify it returns.
        assert not result.empty


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


class TestSearch:
    @pytest.mark.asyncio()
    async def test_search_returns_matching_entities(self, graph: MemoryBackedKnowledgeGraph) -> None:
        """search returns entities whose text matches the query."""
        await graph.add_entity(entity=_make_entity(entity_id="e1", name="Summarizer", description="text"))
        await graph.add_entity(entity=_make_entity(entity_id="e2", name="Planner", description="plans"))

        results = await graph.search(query="Summarizer")
        assert any(e.id == "e1" for e in results)

    @pytest.mark.asyncio()
    async def test_search_filters_by_entity_type(self, graph: MemoryBackedKnowledgeGraph) -> None:
        """search with entity_type filter excludes non-matching types."""
        await graph.add_entity(
            entity=_make_entity(entity_id="t1", entity_type=EntityType.TOOL, name="MyTool")
        )
        await graph.add_entity(
            entity=_make_entity(entity_id="a1", entity_type=EntityType.AGENT, name="MyAgent")
        )

        results = await graph.search(query="My", entity_type=EntityType.TOOL)
        for entity in results:
            assert entity.type == EntityType.TOOL

    @pytest.mark.asyncio()
    async def test_search_respects_limit(self, graph: MemoryBackedKnowledgeGraph) -> None:
        """search returns at most `limit` entities."""
        for i in range(5):
            await graph.add_entity(entity=_make_entity(entity_id=f"e-{i}", name=f"Entity{i}"))

        results = await graph.search(query="Entity", limit=2)
        assert len(results) <= 2

    @pytest.mark.asyncio()
    async def test_search_excludes_relations_and_indexes(self, graph: MemoryBackedKnowledgeGraph) -> None:
        """search only returns entity items, not relation or index items."""
        await graph.add_entity(entity=_make_entity(entity_id="e1", name="E1"))
        await graph.add_entity(entity=_make_entity(entity_id="e2", name="E2"))
        await graph.add_relation(relation=_make_relation(source_id="e1", target_id="e2"))

        results = await graph.search(query="e1")
        for entity in results:
            assert not entity.id.startswith("kg:rel:")
            assert not entity.id.startswith("kg:index:")


# ---------------------------------------------------------------------------
# remove_entity
# ---------------------------------------------------------------------------


class TestRemoveEntity:
    @pytest.mark.asyncio()
    async def test_remove_existing_entity(self, graph: MemoryBackedKnowledgeGraph) -> None:
        """remove_entity returns True and entity is gone."""
        await graph.add_entity(entity=_make_entity(entity_id="rm-1"))
        removed = await graph.remove_entity(entity_id="rm-1")
        assert removed is True
        assert await graph.get_entity(entity_id="rm-1") is None

    @pytest.mark.asyncio()
    async def test_remove_nonexistent_returns_false(self, graph: MemoryBackedKnowledgeGraph) -> None:
        """remove_entity returns False for nonexistent entity."""
        removed = await graph.remove_entity(entity_id="ghost")
        assert removed is False

    @pytest.mark.asyncio()
    async def test_remove_cleans_up_relations_and_indexes(
        self,
        graph: MemoryBackedKnowledgeGraph,
        fake_memory: FakeMemoryManager,
    ) -> None:
        """Removing an entity also removes its relations and cleans peer indexes."""
        await graph.add_entity(entity=_make_entity(entity_id="a", name="A"))
        await graph.add_entity(entity=_make_entity(entity_id="b", name="B"))
        await graph.add_relation(relation=_make_relation(source_id="a", target_id="b"))

        await graph.remove_entity(entity_id="a")

        # Entity gone
        assert await graph.get_entity(entity_id="a") is None

        # Relation gone
        rel_key = "kg:rel:a:uses:b"
        assert await fake_memory.recall_by_key(scope=MemoryScope.PROJECT, key=rel_key) is None

        # Index for "a" gone
        assert await fake_memory.recall_by_key(scope=MemoryScope.PROJECT, key="kg:index:a") is None

        # Peer "b" index no longer references the deleted relation
        b_idx = await fake_memory.recall_by_key(scope=MemoryScope.PROJECT, key="kg:index:b")
        if b_idx is not None:
            assert rel_key not in b_idx.value.get("relation_keys", [])


# ---------------------------------------------------------------------------
# _entity_from_dict / _relation_from_dict round-trips
# ---------------------------------------------------------------------------


class TestDictRoundTrips:
    def test_entity_round_trip(self) -> None:
        """KGEntity -> to_dict -> _entity_from_dict preserves fields."""
        original = _make_entity(
            entity_id="rt-1",
            entity_type=EntityType.MODULE,
            name="CoreModule",
            description="the core",
        )
        data = original.to_dict()
        restored = MemoryBackedKnowledgeGraph._entity_from_dict(data=data)

        assert restored.id == original.id
        assert restored.type == original.type
        assert restored.name == original.name
        assert restored.description == original.description
        assert restored.created_at == original.created_at

    def test_relation_round_trip(self) -> None:
        """KGRelation -> to_dict -> _relation_from_dict preserves fields."""
        original = _make_relation(source_id="s1", target_id="t1", rel_type=RelationType.IMPLEMENTS)
        data = original.to_dict()
        restored = MemoryBackedKnowledgeGraph._relation_from_dict(data=data)

        assert restored.source_id == original.source_id
        assert restored.target_id == original.target_id
        assert restored.type == original.type
        assert restored.created_at == original.created_at


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestFactory:
    def test_create_knowledge_graph(self) -> None:
        """create_knowledge_graph returns a MemoryBackedKnowledgeGraph."""
        mm = FakeMemoryManager()
        kg = create_knowledge_graph(memory_manager=mm)
        assert isinstance(kg, MemoryBackedKnowledgeGraph)
        assert isinstance(kg, KnowledgeGraph)
