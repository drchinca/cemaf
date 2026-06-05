"""Hub & Spoke KG tests — covers SPEC-07 §4 scenarios + properties."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event
from cemaf.knowledge.hub_spoke import (
    KG_INVALIDATION_EVENT_TYPE,
    HubKnowledgeGraph,
    InvalidationKind,
    KGInvalidationEvent,
    LocalSpokeCache,
    SpokeCacheConfig,
    create_hub_spoke_kg,
)
from cemaf.knowledge.models import (
    EntityType,
    KGEntity,
    KGQueryResult,
    KGRelation,
    RelationType,
)


class FakeKG:
    """In-memory fake of a `KnowledgeGraph` for testing."""

    def __init__(self) -> None:
        self.entities: dict[str, KGEntity] = {}
        self.relations: list[KGRelation] = []
        self.get_calls: int = 0
        self.unreachable: bool = False

    async def add_entity(self, entity: KGEntity) -> None:
        self.entities[entity.id] = entity

    async def add_relation(self, relation: KGRelation) -> None:
        self.relations.append(relation)

    async def get_entity(self, entity_id: str) -> KGEntity | None:
        if self.unreachable:
            raise RuntimeError("hub unreachable")
        self.get_calls += 1
        return self.entities.get(entity_id)

    async def query_neighbors(
        self,
        entity_id: str,
        relation_type: RelationType | None = None,
        depth: int = 1,
    ) -> KGQueryResult:
        return KGQueryResult(entities=(), relations=())

    async def search(
        self,
        query: str,
        entity_type: EntityType | None = None,
        limit: int = 10,
    ) -> tuple[KGEntity, ...]:
        return ()

    async def remove_entity(self, entity_id: str) -> bool:
        return self.entities.pop(entity_id, None) is not None


def _entity(id_: str = "e1", name: str = "Entity 1") -> KGEntity:
    return KGEntity(id=id_, type=EntityType.AGENT, name=name)


@pytest.fixture
def fake_kg() -> FakeKG:
    return FakeKG()


@pytest.fixture
def event_bus() -> InMemoryEventBus:
    return InMemoryEventBus()


class TestSpokeCache:
    @pytest.mark.asyncio
    async def test_cache_hit_on_second_read(self, fake_kg: FakeKG, event_bus: InMemoryEventBus) -> None:
        await fake_kg.add_entity(_entity())
        hub, spokes = create_hub_spoke_kg(
            backing_kg=fake_kg,
            event_bus=event_bus,
            spoke_configs={"s1": SpokeCacheConfig()},
        )
        s1 = spokes["s1"]
        await s1.get_entity("e1")
        await s1.get_entity("e1")
        stats = await s1.stats()
        assert stats.hits == 1
        assert stats.misses == 1
        assert stats.hit_rate == pytest.approx(0.5)
        assert fake_kg.get_calls == 1

    @pytest.mark.asyncio
    async def test_write_publishes_invalidation(self, fake_kg: FakeKG, event_bus: InMemoryEventBus) -> None:
        hub, spokes = create_hub_spoke_kg(
            backing_kg=fake_kg,
            event_bus=event_bus,
            spoke_configs={"s1": SpokeCacheConfig(), "s2": SpokeCacheConfig()},
        )
        s1, s2 = spokes["s1"], spokes["s2"]
        await fake_kg.add_entity(_entity())
        await s1.get_entity("e1")
        await s2.get_entity("e1")

        await hub.add_entity(_entity(name="Renamed"))
        assert (await s1.stats()).invalidations_received == 1
        assert (await s2.stats()).invalidations_received == 1

    @pytest.mark.asyncio
    async def test_evict_after_invalidation(self, fake_kg: FakeKG, event_bus: InMemoryEventBus) -> None:
        hub, spokes = create_hub_spoke_kg(
            backing_kg=fake_kg, event_bus=event_bus, spoke_configs={"s1": SpokeCacheConfig()}
        )
        s1 = spokes["s1"]
        await fake_kg.add_entity(_entity())
        await s1.get_entity("e1")  # cached
        await s1.invalidate(KGInvalidationEvent(kind=InvalidationKind.ENTITY_UPDATED, entity_ids=("e1",)))
        before = fake_kg.get_calls
        await s1.get_entity("e1")
        assert fake_kg.get_calls == before + 1  # forced miss

    @pytest.mark.asyncio
    async def test_add_relation_invalidates_both_endpoints(
        self, fake_kg: FakeKG, event_bus: InMemoryEventBus
    ) -> None:
        hub, spokes = create_hub_spoke_kg(
            backing_kg=fake_kg, event_bus=event_bus, spoke_configs={"s1": SpokeCacheConfig()}
        )
        s1 = spokes["s1"]
        await fake_kg.add_entity(_entity("a"))
        await fake_kg.add_entity(_entity("b"))
        await s1.get_entity("a")
        await s1.get_entity("b")

        await hub.add_relation(KGRelation(source_id="a", target_id="b", type=RelationType.DEPENDS_ON))

        before = fake_kg.get_calls
        await s1.get_entity("a")
        await s1.get_entity("b")
        assert fake_kg.get_calls == before + 2  # both forced misses

    @pytest.mark.asyncio
    async def test_negative_cache_invalidated_on_add(
        self, fake_kg: FakeKG, event_bus: InMemoryEventBus
    ) -> None:
        hub, spokes = create_hub_spoke_kg(
            backing_kg=fake_kg,
            event_bus=event_bus,
            spoke_configs={"s1": SpokeCacheConfig(enable_negative_cache=True)},
        )
        s1 = spokes["s1"]
        assert await s1.get_entity("ghost") is None  # cached negative
        before = fake_kg.get_calls
        assert await s1.get_entity("ghost") is None  # served from cache
        assert fake_kg.get_calls == before  # no extra hub call

        await hub.add_entity(_entity("ghost", name="Ghost"))
        result = await s1.get_entity("ghost")
        assert result is not None and result.name == "Ghost"

    @pytest.mark.asyncio
    async def test_max_entities_cap(self, fake_kg: FakeKG, event_bus: InMemoryEventBus) -> None:
        hub, spokes = create_hub_spoke_kg(
            backing_kg=fake_kg,
            event_bus=event_bus,
            spoke_configs={"s1": SpokeCacheConfig(max_entities=10)},
        )
        s1 = spokes["s1"]
        for i in range(12):
            await fake_kg.add_entity(_entity(f"e{i}"))
            await s1.get_entity(f"e{i}")
        stats = await s1.stats()
        assert stats.size == 10

    @pytest.mark.asyncio
    async def test_lru_eviction_order(self, fake_kg: FakeKG, event_bus: InMemoryEventBus) -> None:
        hub, spokes = create_hub_spoke_kg(
            backing_kg=fake_kg,
            event_bus=event_bus,
            spoke_configs={"s1": SpokeCacheConfig(max_entities=10)},
        )
        s1 = spokes["s1"]
        for i in range(10):
            await fake_kg.add_entity(_entity(f"e{i}"))
            await s1.get_entity(f"e{i}")
        await fake_kg.add_entity(_entity("e10"))
        await s1.get_entity("e10")  # forces eviction of e0 (oldest)

        # e1..e10 are still in cache; e0 was evicted
        for i in range(1, 11):
            before_hits = (await s1.stats()).hits
            await s1.get_entity(f"e{i}")
            assert (await s1.stats()).hits == before_hits + 1, f"e{i} should be a hit"
        # e0 must miss
        before_misses = (await s1.stats()).misses
        await s1.get_entity("e0")
        assert (await s1.stats()).misses == before_misses + 1

    @pytest.mark.asyncio
    async def test_ttl_expiry(self, fake_kg: FakeKG, event_bus: InMemoryEventBus) -> None:
        hub, spokes = create_hub_spoke_kg(
            backing_kg=fake_kg,
            event_bus=event_bus,
            spoke_configs={"s1": SpokeCacheConfig(ttl=timedelta(milliseconds=20))},
        )
        s1 = spokes["s1"]
        await fake_kg.add_entity(_entity())
        await s1.get_entity("e1")
        await asyncio.sleep(0.05)
        before = fake_kg.get_calls
        await s1.get_entity("e1")
        assert fake_kg.get_calls == before + 1  # expired → forced miss

    @pytest.mark.asyncio
    async def test_writes_persist_via_hub(self, fake_kg: FakeKG, event_bus: InMemoryEventBus) -> None:
        hub, spokes = create_hub_spoke_kg(
            backing_kg=fake_kg, event_bus=event_bus, spoke_configs={"s1": SpokeCacheConfig()}
        )
        await hub.add_entity(_entity())
        assert "e1" in fake_kg.entities
        # spoke does NOT pre-populate
        assert (await spokes["s1"].stats()).size == 0

    @pytest.mark.asyncio
    async def test_hub_failure_isolates_cached_reads(
        self, fake_kg: FakeKG, event_bus: InMemoryEventBus
    ) -> None:
        hub, spokes = create_hub_spoke_kg(
            backing_kg=fake_kg, event_bus=event_bus, spoke_configs={"s1": SpokeCacheConfig()}
        )
        s1 = spokes["s1"]
        await fake_kg.add_entity(_entity())
        await s1.get_entity("e1")
        fake_kg.unreachable = True
        # cached value still served
        result = await s1.get_entity("e1")
        assert result is not None and result.id == "e1"

    @pytest.mark.asyncio
    async def test_hub_failure_on_miss_raises(self, fake_kg: FakeKG, event_bus: InMemoryEventBus) -> None:
        hub, spokes = create_hub_spoke_kg(
            backing_kg=fake_kg, event_bus=event_bus, spoke_configs={"s1": SpokeCacheConfig()}
        )
        fake_kg.unreachable = True
        with pytest.raises(RuntimeError, match="unreachable"):
            await spokes["s1"].get_entity("never-cached")

    @pytest.mark.asyncio
    async def test_unsubscribed_spoke_does_not_receive_events(
        self, fake_kg: FakeKG, event_bus: InMemoryEventBus
    ) -> None:
        hub, spokes = create_hub_spoke_kg(
            backing_kg=fake_kg, event_bus=event_bus, spoke_configs={"s1": SpokeCacheConfig()}
        )
        s1 = spokes["s1"]
        hub.unsubscribe(s1)
        await hub.add_entity(_entity())
        assert (await s1.stats()).invalidations_received == 0

    @pytest.mark.asyncio
    async def test_spoke_handler_error_is_suppressed(
        self, fake_kg: FakeKG, event_bus: InMemoryEventBus
    ) -> None:
        """SPEC-07 Inv 8: spoke handlers MUST NOT raise.

        `LocalSpokeCache.invalidate` swallows internal errors and logs them; the
        hub write completes regardless.
        """
        hub = HubKnowledgeGraph(backing_kg=fake_kg, event_bus=event_bus)
        spoke = LocalSpokeCache(spoke_id="ok", hub=hub)
        # Force an internal error path: corrupt the entries dict so .pop raises
        spoke._entries = None  # type: ignore[assignment]
        hub.subscribe(spoke)

        await hub.add_entity(_entity())  # must not raise
        assert "e1" in fake_kg.entities

    @pytest.mark.asyncio
    async def test_concurrent_fetch_does_not_insert_after_invalidation(
        self, fake_kg: FakeKG, event_bus: InMemoryEventBus
    ) -> None:
        """Property: in-flight fetch + invalidation must NOT cache stale value."""

        await fake_kg.add_entity(_entity())
        gate = asyncio.Event()

        slow_kg_get = fake_kg.get_entity

        async def slow_get(entity_id: str) -> KGEntity | None:
            await gate.wait()
            return await slow_kg_get(entity_id)

        fake_kg.get_entity = slow_get  # type: ignore[method-assign]
        hub = HubKnowledgeGraph(backing_kg=fake_kg, event_bus=event_bus)
        spoke = LocalSpokeCache(spoke_id="s1", hub=hub, config=SpokeCacheConfig())
        hub.subscribe(spoke)

        get_task = asyncio.create_task(spoke.get_entity("e1"))
        await asyncio.sleep(0)  # allow task to start, enter _inflight
        await spoke.invalidate(KGInvalidationEvent(kind=InvalidationKind.ENTITY_UPDATED, entity_ids=("e1",)))
        gate.set()
        result = await get_task

        assert result is not None  # value still returned to caller
        assert (await spoke.stats()).size == 0  # but NOT cached

    @pytest.mark.asyncio
    async def test_invalidation_event_published_to_event_bus(
        self, fake_kg: FakeKG, event_bus: InMemoryEventBus
    ) -> None:
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        event_bus.subscribe(KG_INVALIDATION_EVENT_TYPE, handler)
        hub, _ = create_hub_spoke_kg(backing_kg=fake_kg, event_bus=event_bus, spoke_configs={})
        await hub.add_entity(_entity())
        await asyncio.sleep(0)  # let the bus dispatch
        assert len(received) == 1
        assert received[0].payload["kind"] == "entity_updated"
        assert received[0].payload["entity_ids"] == ["e1"]
