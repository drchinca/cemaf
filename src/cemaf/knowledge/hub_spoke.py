"""Hub & Spoke Knowledge Graph (SPEC-07).

Promotes a `KnowledgeGraph` from a single hub to a hub-and-spoke topology:
spokes hold a bounded LRU cache of point lookups (`get_entity`); writes
always go to the hub, which publishes `KGInvalidationEvent`s on the
EventBus so spokes can evict stale entries. TTL is the safety net when
events are dropped.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from cemaf.core.utils import utc_now
from cemaf.events.protocols import Event, EventBus
from cemaf.knowledge.models import (
    EntityType,
    KGEntity,
    KGQueryResult,
    KGRelation,
    RelationType,
)
from cemaf.knowledge.protocols import KnowledgeGraph

_log = logging.getLogger(__name__)

KG_INVALIDATION_EVENT_TYPE = "kg.invalidation"


class InvalidationKind(StrEnum):
    ENTITY_UPDATED = "entity_updated"
    ENTITY_REMOVED = "entity_removed"
    RELATION_ADDED = "relation_added"


@dataclass(frozen=True, slots=True)
class KGInvalidationEvent:
    kind: InvalidationKind
    entity_ids: tuple[str, ...]
    correlation_id: str = ""

    def to_payload(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "entity_ids": list(self.entity_ids),
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> KGInvalidationEvent:
        raw_ids = payload.get("entity_ids", [])
        ids = raw_ids if isinstance(raw_ids, list) else []
        return cls(
            kind=InvalidationKind(str(payload["kind"])),
            entity_ids=tuple(str(x) for x in ids),
            correlation_id=str(payload.get("correlation_id", "")),
        )


@dataclass(frozen=True, slots=True)
class SpokeCacheConfig:
    max_entities: int = 1024
    ttl: timedelta = timedelta(minutes=5)
    enable_negative_cache: bool = True


@dataclass(slots=True)
class SpokeStats:
    hits: int = 0
    misses: int = 0
    invalidations_received: int = 0
    size: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    def snapshot(self) -> SpokeStats:
        return SpokeStats(
            hits=self.hits,
            misses=self.misses,
            invalidations_received=self.invalidations_received,
            size=self.size,
        )


@dataclass(slots=True)
class _Entry:
    value: KGEntity | None
    inserted_at: float


class LocalSpokeCache:
    """Bounded LRU read-through cache fronting a `KnowledgeGraph` (SPEC-07 §2)."""

    def __init__(
        self,
        *,
        spoke_id: str,
        hub: KnowledgeGraph,
        config: SpokeCacheConfig | None = None,
    ) -> None:
        self.spoke_id = spoke_id
        self.config = config or SpokeCacheConfig()
        self._hub = hub
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._stats = SpokeStats()
        self._inflight: set[str] = set()

    async def get_entity(self, entity_id: str) -> KGEntity | None:
        entry = self._entries.get(entity_id)
        if entry is not None and not self._is_expired(entry):
            self._entries.move_to_end(entity_id)
            self._stats.hits += 1
            return entry.value
        if entry is not None and self._is_expired(entry):
            self._entries.pop(entity_id, None)

        self._stats.misses += 1
        self._inflight.add(entity_id)
        try:
            value = await self._hub.get_entity(entity_id)
        finally:
            still_inflight = entity_id in self._inflight
            self._inflight.discard(entity_id)

        # If invalidation arrived while in-flight, the entity was removed from
        # _inflight by invalidate(); do NOT cache the (possibly-stale) value.
        if not still_inflight:
            return value

        self._insert(entity_id=entity_id, value=value)
        return value

    async def invalidate(self, event: KGInvalidationEvent) -> None:
        try:
            self._stats.invalidations_received += 1
            for entity_id in event.entity_ids:
                self._entries.pop(entity_id, None)
                self._inflight.discard(entity_id)
            self._stats.size = len(self._entries)
        except Exception:
            _log.exception("spoke %s invalidation handler error (suppressed)", self.spoke_id)

    async def stats(self) -> SpokeStats:
        self._stats.size = len(self._entries)
        return self._stats.snapshot()

    def _insert(self, *, entity_id: str, value: KGEntity | None) -> None:
        if value is None and not self.config.enable_negative_cache:
            return
        if entity_id in self._entries:
            self._entries.move_to_end(entity_id)
            self._entries[entity_id] = _Entry(value=value, inserted_at=self._now())
            return
        if len(self._entries) >= self.config.max_entities:
            self._entries.popitem(last=False)
        self._entries[entity_id] = _Entry(value=value, inserted_at=self._now())
        self._stats.size = len(self._entries)

    def _is_expired(self, entry: _Entry) -> bool:
        ttl_seconds = self.config.ttl.total_seconds()
        return (self._now() - entry.inserted_at) >= ttl_seconds

    @staticmethod
    def _now() -> float:
        return utc_now().timestamp()


class HubKnowledgeGraph:
    """Hub: a `KnowledgeGraph` decorator that emits invalidation events on writes."""

    def __init__(self, *, backing_kg: KnowledgeGraph, event_bus: EventBus) -> None:
        self._kg = backing_kg
        self._bus = event_bus
        self._spokes: list[LocalSpokeCache] = []

    def subscribe(self, spoke: LocalSpokeCache) -> None:
        self._spokes.append(spoke)

    def unsubscribe(self, spoke: LocalSpokeCache) -> None:
        self._spokes = [s for s in self._spokes if s is not spoke]

    async def add_entity(self, entity: KGEntity) -> None:
        await self._kg.add_entity(entity)
        await self._publish(
            KGInvalidationEvent(
                kind=InvalidationKind.ENTITY_UPDATED,
                entity_ids=(entity.id,),
            )
        )

    async def add_relation(self, relation: KGRelation) -> None:
        await self._kg.add_relation(relation)
        await self._publish(
            KGInvalidationEvent(
                kind=InvalidationKind.RELATION_ADDED,
                entity_ids=(relation.source_id, relation.target_id),
            )
        )

    async def get_entity(self, entity_id: str) -> KGEntity | None:
        return await self._kg.get_entity(entity_id)

    async def query_neighbors(
        self,
        entity_id: str,
        relation_type: RelationType | None = None,
        depth: int = 1,
    ) -> KGQueryResult:
        return await self._kg.query_neighbors(entity_id=entity_id, relation_type=relation_type, depth=depth)

    async def search(
        self,
        query: str,
        entity_type: EntityType | None = None,
        limit: int = 10,
    ) -> tuple[KGEntity, ...]:
        return await self._kg.search(query=query, entity_type=entity_type, limit=limit)

    async def remove_entity(self, entity_id: str) -> bool:
        result = await self._kg.remove_entity(entity_id)
        if result:
            await self._publish(
                KGInvalidationEvent(
                    kind=InvalidationKind.ENTITY_REMOVED,
                    entity_ids=(entity_id,),
                )
            )
        return result

    async def _publish(self, event: KGInvalidationEvent) -> None:
        for spoke in list(self._spokes):
            await spoke.invalidate(event)
        await self._bus.publish(
            Event.create(
                type=KG_INVALIDATION_EVENT_TYPE,
                payload=event.to_payload(),
                source="kg.hub",
                correlation_id=event.correlation_id or None,
            )
        )


def create_hub_spoke_kg(
    *,
    backing_kg: KnowledgeGraph,
    event_bus: EventBus,
    spoke_configs: Mapping[str, SpokeCacheConfig] | None = None,
) -> tuple[HubKnowledgeGraph, Mapping[str, LocalSpokeCache]]:
    """Wire a hub around `backing_kg` and create one spoke per `spoke_configs` key."""
    hub = HubKnowledgeGraph(backing_kg=backing_kg, event_bus=event_bus)
    spokes: dict[str, LocalSpokeCache] = {}
    for spoke_id, cfg in (spoke_configs or {}).items():
        spoke = LocalSpokeCache(spoke_id=spoke_id, hub=hub, config=cfg)
        hub.subscribe(spoke)
        spokes[spoke_id] = spoke
    return hub, spokes


__all__ = [
    "HubKnowledgeGraph",
    "InvalidationKind",
    "KGInvalidationEvent",
    "KG_INVALIDATION_EVENT_TYPE",
    "LocalSpokeCache",
    "SpokeCacheConfig",
    "SpokeStats",
    "create_hub_spoke_kg",
]
