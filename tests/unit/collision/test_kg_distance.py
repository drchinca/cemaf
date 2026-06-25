"""SPEC-12 — unit tests for build_kg_dep_distance (KnowledgeGraph → sync dep-distance bridge).

Asserts the raw hop-count floats directly — the integer hop count is the whole reason this
module exists over a boolean reachability predicate, so it must be pinned, not merely shown
to decay.
"""

import pytest

from cemaf.collision import build_kg_dep_distance
from cemaf.knowledge.factories import create_knowledge_graph
from cemaf.knowledge.models import EntityType, KGEntity, KGRelation, RelationType
from cemaf.memory.factories import create_memory_manager

INF = float("inf")


async def _kg(*edges: tuple[str, str]):
    kg = create_knowledge_graph(memory_manager=create_memory_manager())
    nodes = {n for edge in edges for n in edge}
    for node in nodes:
        await kg.add_entity(KGEntity(id=node, type=EntityType.MODULE, name=node))
    for source, target in edges:
        await kg.add_relation(KGRelation(source_id=source, target_id=target, type=RelationType.DEPENDS_ON))
    return kg


class TestKgDepDistance:
    @pytest.mark.asyncio
    async def test_direct_edge_is_one_hop(self) -> None:
        kg = await _kg(("a", "b"))
        dep = await build_kg_dep_distance(knowledge_graph=kg, entity_ids=("a", "b"))
        assert dep("a", "b") == 1.0

    @pytest.mark.asyncio
    async def test_transitive_edge_is_two_hops(self) -> None:
        kg = await _kg(("a", "b"), ("b", "c"))
        dep = await build_kg_dep_distance(knowledge_graph=kg, entity_ids=("a", "b", "c"))
        assert dep("a", "b") == 1.0
        assert dep("a", "c") == 2.0

    @pytest.mark.asyncio
    async def test_max_depth_cutoff_is_unreachable(self) -> None:
        """A chain longer than max_depth ⇒ the far node is +inf (unreachable within budget)."""
        kg = await _kg(("n0", "n1"), ("n1", "n2"), ("n2", "n3"))
        dep = await build_kg_dep_distance(
            knowledge_graph=kg, entity_ids=("n0", "n1", "n2", "n3"), max_depth=2
        )
        assert dep("n0", "n1") == 1.0
        assert dep("n0", "n2") == 2.0
        assert dep("n0", "n3") == INF  # 3 hops > max_depth=2

    @pytest.mark.asyncio
    async def test_max_depth_zero_raises(self) -> None:
        kg = await _kg(("a", "b"))
        with pytest.raises(ValueError, match="max_depth must be >= 1"):
            await build_kg_dep_distance(knowledge_graph=kg, entity_ids=("a", "b"), max_depth=0)

    @pytest.mark.asyncio
    async def test_entity_not_in_graph_is_inf(self) -> None:
        kg = await _kg(("a", "b"))
        dep = await build_kg_dep_distance(knowledge_graph=kg, entity_ids=("ghost", "a"))
        assert dep("ghost", "a") == INF

    @pytest.mark.asyncio
    async def test_same_node_is_inf(self) -> None:
        """path_a == path_b is the overlap channel's job, never the dependency channel."""
        kg = await _kg(("a", "b"))
        dep = await build_kg_dep_distance(knowledge_graph=kg, entity_ids=("a", "b"))
        assert dep("a", "a") == INF

    @pytest.mark.asyncio
    async def test_empty_entity_ids_all_inf(self) -> None:
        kg = await _kg(("a", "b"))
        dep = await build_kg_dep_distance(knowledge_graph=kg, entity_ids=())
        assert dep("a", "b") == INF

    @pytest.mark.asyncio
    async def test_duplicate_entity_ids_preserve_correctness(self) -> None:
        kg = await _kg(("a", "b"))
        dep = await build_kg_dep_distance(knowledge_graph=kg, entity_ids=("a", "a", "b"))
        assert dep("a", "b") == 1.0

    @pytest.mark.asyncio
    async def test_distance_is_symmetric(self) -> None:
        """The KG index is bidirectional, so the snapshot is symmetric — a single A→B edge
        yields dep(a,b) == dep(b,a). Guards the min(dep(a,b),dep(b,a)) logic in risk.py."""
        kg = await _kg(("a", "b"))
        dep = await build_kg_dep_distance(knowledge_graph=kg, entity_ids=("a", "b"))
        assert dep("a", "b") == dep("b", "a") == 1.0
