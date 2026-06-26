"""SPEC-12 integration — collision in CEMAF terms: real KnowledgeGraph dependency channel
and true asyncio.gather cohort concurrency through the coordinator.

These exercise the parts the lightweight coordinator test can't: the dependency channel wired
to a genuine MemoryBackedKnowledgeGraph via build_kg_dep_distance, and N agents racing through
register/advise under real concurrency with the cohort barrier.
"""

import asyncio

import pytest

from cemaf.collision import (
    AdvisoryLevel,
    AgentWriteSet,
    TcasCollisionPolicy,
    WriteItem,
    build_kg_dep_distance,
    collision_risk,
    create_collision_coordinator,
    emit_advisory,
)
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType
from cemaf.knowledge.factories import create_knowledge_graph
from cemaf.knowledge.models import EntityType, KGEntity, KGRelation, RelationType
from cemaf.memory.factories import create_memory_manager


def _ws(agent_id: str, *paths: str, started_at: float = 0.0) -> AgentWriteSet:
    return AgentWriteSet(
        agent_id=agent_id,
        items=tuple(WriteItem(path=p) for p in paths),
        started_at=started_at,
    )


async def _kg_with_chain(*edges: tuple[str, str]):
    """Build a real KG with the given dependency edges (source DEPENDS_ON target)."""
    kg = create_knowledge_graph(memory_manager=create_memory_manager())
    nodes = {n for edge in edges for n in edge}
    for node in nodes:
        await kg.add_entity(KGEntity(id=node, type=EntityType.MODULE, name=node))
    for source, target in edges:
        await kg.add_relation(KGRelation(source_id=source, target_id=target, type=RelationType.DEPENDS_ON))
    return kg


class TestKnowledgeGraphDependencyChannel:
    @pytest.mark.asyncio
    async def test_direct_dependency_fires_channel(self) -> None:
        """A real KG edge A→B ⇒ dependency channel > 0 for agents writing A and B (disjoint paths)."""
        kg = await _kg_with_chain(("mod_a", "mod_b"))
        dep_distance = await build_kg_dep_distance(knowledge_graph=kg, entity_ids=("mod_a", "mod_b"))
        a = _ws("x", "mod_a")
        b = _ws("y", "mod_b")
        result = collision_risk(a, b, dep_distance=dep_distance)
        assert result.channels.overlap == 0.0  # disjoint paths
        assert result.channels.dependency > 0.0  # but coupled in the graph

    @pytest.mark.asyncio
    async def test_transitive_dependency_decays_with_hops(self) -> None:
        """A→B→C: the 2-hop pair couples less than the 1-hop pair (gamma decay)."""
        kg = await _kg_with_chain(("mod_a", "mod_b"), ("mod_b", "mod_c"))
        dep = await build_kg_dep_distance(knowledge_graph=kg, entity_ids=("mod_a", "mod_b", "mod_c"))
        # Pin the integer hop counts at the point the risk math consumes them.
        assert dep("mod_a", "mod_b") == 1.0
        assert dep("mod_a", "mod_c") == 2.0
        one_hop = collision_risk(_ws("x", "mod_a"), _ws("y", "mod_b"), dep_distance=dep)
        two_hop = collision_risk(_ws("x", "mod_a"), _ws("z", "mod_c"), dep_distance=dep)
        assert one_hop.channels.dependency > two_hop.channels.dependency > 0.0

    @pytest.mark.asyncio
    async def test_unrelated_modules_no_dependency(self) -> None:
        """Two modules with no path between them ⇒ dependency channel 0."""
        kg = await _kg_with_chain(("mod_a", "mod_b"))
        await kg.add_entity(KGEntity(id="island", type=EntityType.MODULE, name="island"))
        dep = await build_kg_dep_distance(knowledge_graph=kg, entity_ids=("mod_a", "island"))
        result = collision_risk(_ws("x", "mod_a"), _ws("y", "island"), dep_distance=dep)
        assert result.channels.dependency == 0.0

    @pytest.mark.asyncio
    async def test_policy_uses_kg_distance_for_advisory(self) -> None:
        """The KG-backed dep_distance plugs straight into TcasCollisionPolicy."""
        kg = await _kg_with_chain(("mod_a", "mod_b"))
        dep = await build_kg_dep_distance(knowledge_graph=kg, entity_ids=("mod_a", "mod_b"))
        policy = TcasCollisionPolicy(dep_distance=dep)
        advisory = policy.advise(_ws("x", "mod_a", started_at=1.0), _ws("y", "mod_b", started_at=2.0))
        # dependency channel (omega 0.9) alone pushes a direct-edge pair into at least an advisory
        assert advisory.level in (AdvisoryLevel.TRAFFIC_ADVISORY, AdvisoryLevel.RESOLUTION_ADVISORY)


class TestCohortConcurrency:
    @pytest.mark.asyncio
    async def test_large_cohort_races_to_deterministic_resolution(self) -> None:
        """N agents on the same path race through register/advise under real asyncio.gather;
        exactly one holds, the rest steer, and every run picks the same holder."""
        cohort = 12
        coord = create_collision_coordinator(cohort_size=cohort)
        bus = InMemoryEventBus()
        conflicts: list[Event] = []
        bus.subscribe(EventType.CONTEXT_CONFLICT, lambda e: conflicts.append(e))

        async def agent(i: int) -> str:
            # earlier started_at for lower i → lowest i should hold right-of-way
            await coord.register(_ws(f"agent_{i:02d}", "draft.body", started_at=float(i + 1)))
            adv = await coord.advise_against_cohort(f"agent_{i:02d}")
            await emit_advisory(event_bus=bus, advisory=adv, agent_id=f"agent_{i:02d}")
            return adv.hold or ""

        holders = await asyncio.gather(*(agent(i) for i in range(cohort)))
        # Every agent agrees on a single holder (the earliest-started agent_00).
        assert set(holders) == {"agent_00"}
        # Every agent emitted a conflict event (all at RA on the shared path).
        assert len(conflicts) == cohort
        assert all(e.payload["hold"] == "agent_00" for e in conflicts)

    @pytest.mark.asyncio
    async def test_repeated_runs_are_stable(self) -> None:
        """Determinism under concurrency — identical holder across many runs at full cohort size.

        Repeats at cohort=12 (a wide race window) so a 1-in-N ordering race would surface, not
        hide behind a 2-run check at a small cohort.
        """
        cohort = 12

        async def run_once() -> set[str]:
            coord = create_collision_coordinator(cohort_size=cohort)

            async def agent(i: int) -> str:
                await coord.register(_ws(f"a{i:02d}", "shared.key", started_at=float(i + 1)))
                adv = await coord.advise_against_cohort(f"a{i:02d}")
                return adv.hold or ""

            return set(await asyncio.gather(*(agent(i) for i in range(cohort))))

        holders = {tuple(sorted(await run_once())) for _ in range(25)}
        # Every one of the 25 concurrent runs picked the same single holder.
        assert holders == {("a00",)}
