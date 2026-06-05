"""Integration test: cemaf.knowledge.hub_spoke over a REAL MemoryBackedKnowledgeGraph.

Proves SPEC-07 is a live seam: spokes front a real `MemoryBackedKnowledgeGraph`
(backed by a real `DefaultMemoryManager` + `InMemoryStore` + vector store), the
hub publishes invalidations on a real `InMemoryEventBus`, and the cache → hub →
store round-trip is exercised end-to-end with no mocks.

Per the house rule (CLAUDE.md): a `to_*()`/decorator seam without a test that
feeds real implementations through it is a dead end, not an integration.
"""

from __future__ import annotations

import asyncio

import pytest

from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event
from cemaf.knowledge.factories import create_knowledge_graph
from cemaf.knowledge.hub_spoke import (
    KG_INVALIDATION_EVENT_TYPE,
    SpokeCacheConfig,
    SpokeReadHubWriteKG,
    create_hub_spoke_kg,
)
from cemaf.knowledge.models import EntityType, KGEntity, KGRelation, RelationType
from cemaf.memory.factories import create_memory_manager


def _entity(id_: str, name: str) -> KGEntity:
    return KGEntity(id=id_, type=EntityType.MODULE, name=name, description=f"{name} module")


@pytest.fixture
def event_bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture
def real_kg():
    """A real MemoryBackedKnowledgeGraph over a fully-wired in-memory MemoryManager."""
    manager = create_memory_manager()
    return create_knowledge_graph(memory_manager=manager)


@pytest.mark.asyncio
async def test_spoke_serves_reads_from_real_kg(real_kg, event_bus: InMemoryEventBus) -> None:
    """First read misses to the real KG; second read is served from the spoke."""
    hub, spokes = create_hub_spoke_kg(
        backing_kg=real_kg,
        event_bus=event_bus,
        spoke_configs={"researcher": SpokeCacheConfig(max_entities=64)},
    )
    s = spokes["researcher"]

    # Write goes through the hub to the real backing store.
    await hub.add_entity(_entity("mod:context", "context"))

    first = await s.get_entity("mod:context")
    second = await s.get_entity("mod:context")

    assert first is not None and first.name == "context"
    assert second is not None and second.id == "mod:context"
    stats = await s.stats()
    assert stats.hits == 1  # second read was a cache hit
    assert stats.misses == 1


@pytest.mark.asyncio
async def test_write_invalidates_spoke_against_real_kg(real_kg, event_bus: InMemoryEventBus) -> None:
    """A hub write updates the real store AND evicts the stale spoke entry."""
    hub, spokes = create_hub_spoke_kg(
        backing_kg=real_kg,
        event_bus=event_bus,
        spoke_configs={"s1": SpokeCacheConfig()},
    )
    s1 = spokes["s1"]

    await hub.add_entity(_entity("mod:memory", "memory"))
    cached = await s1.get_entity("mod:memory")
    assert cached is not None and cached.description == "memory module"

    # Replace the entity through the hub — spoke must evict and re-fetch the new value.
    await hub.add_entity(
        KGEntity(id="mod:memory", type=EntityType.MODULE, name="memory", description="REVISED")
    )
    refreshed = await s1.get_entity("mod:memory")

    assert refreshed is not None
    assert refreshed.description == "REVISED"  # served from the real KG, not stale cache
    # two writes (initial + replacement) each publish one invalidation
    assert (await s1.stats()).invalidations_received == 2


@pytest.mark.asyncio
async def test_add_relation_invalidates_both_endpoints_real(real_kg, event_bus: InMemoryEventBus) -> None:
    hub, spokes = create_hub_spoke_kg(
        backing_kg=real_kg,
        event_bus=event_bus,
        spoke_configs={"s1": SpokeCacheConfig()},
    )
    s1 = spokes["s1"]

    await hub.add_entity(_entity("a", "alpha"))
    await hub.add_entity(_entity("b", "beta"))
    await s1.get_entity("a")
    await s1.get_entity("b")
    hits_before = (await s1.stats()).hits

    await hub.add_relation(KGRelation(source_id="a", target_id="b", type=RelationType.DEPENDS_ON))

    # both endpoints evicted → both reads are misses (no new hits)
    await s1.get_entity("a")
    await s1.get_entity("b")
    assert (await s1.stats()).hits == hits_before


@pytest.mark.asyncio
async def test_invalidation_reaches_non_spoke_subscriber(real_kg, event_bus: InMemoryEventBus) -> None:
    """Non-spoke EventBus subscribers also see kg.invalidation events."""
    received: list[Event] = []

    async def observer(event: Event) -> None:
        received.append(event)

    event_bus.subscribe(KG_INVALIDATION_EVENT_TYPE, observer)
    hub, _ = create_hub_spoke_kg(backing_kg=real_kg, event_bus=event_bus, spoke_configs={})

    await hub.add_entity(_entity("mod:evals", "evals"))
    await asyncio.sleep(0)  # let the bus dispatch

    assert len(received) == 1
    assert received[0].payload["entity_ids"] == ["mod:evals"]
    assert received[0].payload["kind"] == "entity_updated"


@pytest.mark.asyncio
async def test_remove_entity_propagates_to_real_kg_and_spoke(real_kg, event_bus: InMemoryEventBus) -> None:
    hub, spokes = create_hub_spoke_kg(
        backing_kg=real_kg,
        event_bus=event_bus,
        spoke_configs={"s1": SpokeCacheConfig(enable_negative_cache=True)},
    )
    s1 = spokes["s1"]

    await hub.add_entity(_entity("mod:temp", "temp"))
    assert await s1.get_entity("mod:temp") is not None

    removed = await hub.remove_entity("mod:temp")
    assert removed is True

    # spoke evicted on removal; re-fetch from the real KG returns None
    assert await s1.get_entity("mod:temp") is None
    # add_entity (1) + remove_entity (1) = 2 invalidations
    assert (await s1.stats()).invalidations_received == 2


@pytest.mark.asyncio
async def test_two_spokes_share_one_hub(real_kg, event_bus: InMemoryEventBus) -> None:
    """Independent spokes keep independent caches but one shared hub-of-record."""
    hub, spokes = create_hub_spoke_kg(
        backing_kg=real_kg,
        event_bus=event_bus,
        spoke_configs={"researcher": SpokeCacheConfig(), "writer": SpokeCacheConfig()},
    )
    researcher, writer = spokes["researcher"], spokes["writer"]

    await hub.add_entity(_entity("mod:llm", "llm"))
    await researcher.get_entity("mod:llm")
    await writer.get_entity("mod:llm")

    # both cached independently
    assert (await researcher.stats()).size == 1
    assert (await writer.stats()).size == 1

    # a write invalidates both (initial seed write + this replacement = 2 each)
    await hub.add_entity(KGEntity(id="mod:llm", type=EntityType.MODULE, name="llm", description="v2"))
    assert (await researcher.stats()).invalidations_received == 2
    assert (await writer.stats()).invalidations_received == 2


@pytest.mark.asyncio
async def test_meta_executor_wires_hub_spoke_kg() -> None:
    """create_meta_executor(enable_hub_spoke_kg=True) hands meta-agents a spoke facade.

    Composition-root proof: the resolved KG is a SpokeReadHubWriteKG (point reads
    cached), and a real self-audit-style registration succeeds through it.
    """
    from cemaf.agents.registry import AgentRegistry
    from cemaf.audit.factories import create_audit_system
    from cemaf.knowledge.factories import create_knowledge_graph
    from cemaf.meta.bootstrap import MetaServices, create_meta_executor
    from cemaf.orchestration.executor import ExecutorConfig
    from cemaf.orchestration.services import RuntimeServices
    from cemaf.tools.registry import ToolRegistry

    event_bus = InMemoryEventBus()
    manager = create_memory_manager(event_bus=event_bus)
    kg = create_knowledge_graph(memory_manager=manager)
    audit_log, audit_trail = create_audit_system(event_bus=event_bus)

    agent_registry = AgentRegistry()
    tool_registry = ToolRegistry()
    services = RuntimeServices(event_bus=event_bus, memory_manager=manager, knowledge_graph=kg)
    meta_services = MetaServices(
        audit_log=audit_log,
        audit_trail=audit_trail,
        knowledge_graph=kg,
        enable_hub_spoke_kg=True,
        hub_spoke_config=SpokeCacheConfig(max_entities=32),
    )

    executor = create_meta_executor(
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        config=ExecutorConfig(enable_events=False),
        services=services,
        meta_services=meta_services,
    )

    assert executor is not None
    # The KG-backed meta-tool exists and is backed by the spoke facade.
    kg_tool = tool_registry.get("meta_knowledge_graph")
    assert kg_tool is not None
    assert isinstance(kg_tool._knowledge_graph, SpokeReadHubWriteKG)  # type: ignore[attr-defined]
