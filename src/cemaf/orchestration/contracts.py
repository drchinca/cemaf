"""
Control-plane contracts for hyperscale coordination workflows.

These are protocol-first primitives for:
- Queue admission and worker reservations
- Query planning and router directives
- Index/data lifecycle policy evaluation

The contracts are intentionally implementation-agnostic so CEMAF can wire
different backends (Kafka/SQS/NATS, custom planners, ILM/ISM engines) without
changing orchestrator call sites.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

Metadata = dict[str, Any]

__all__ = [
    # Queue
    "QueueItem",
    "QueueReservation",
    "QueueContract",
    # Planner
    "RetrievalMode",
    "PlannerTarget",
    "PlannerRequest",
    "PlannerStep",
    "PlannerPlan",
    "PlannerContract",
    # Lifecycle
    "StorageTier",
    "LifecycleActionType",
    "LifecycleAsset",
    "LifecycleAction",
    "LifecyclePolicyContract",
]


@dataclass(frozen=True)
class QueueItem:
    """A queue unit of work."""

    item_id: str
    topic: str
    payload: Any
    enqueued_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    priority: int = 0
    delivery_attempt: int = 0
    dedupe_key: str | None = None
    metadata: Metadata = field(default_factory=dict)


@dataclass(frozen=True)
class QueueReservation:
    """A leased reservation handed to a worker."""

    reservation_id: str
    item: QueueItem
    worker_id: str
    leased_until: datetime
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: Metadata = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Return True when the reservation lease is already expired."""
        return self.leased_until <= datetime.now(UTC)


@runtime_checkable
class QueueContract(Protocol):
    """
    Queue coordination contract.

    Uses reservation terminology instead of claim terminology to avoid IAM/IDP
    naming collision.
    """

    async def enqueue(self, item: QueueItem) -> str:
        """Insert a new queue item and return its id."""
        ...

    async def reserve(
        self,
        *,
        worker_id: str,
        max_items: int = 1,
        lease_seconds: int = 30,
        topics: tuple[str, ...] = (),
    ) -> tuple[QueueReservation, ...]:
        """Reserve up to `max_items` ready queue items for a worker."""
        ...

    async def complete(self, reservation_id: str) -> bool:
        """Mark a reserved item as successfully processed."""
        ...

    async def retry(
        self,
        reservation_id: str,
        *,
        delay_seconds: int = 0,
        error: str | None = None,
    ) -> bool:
        """Return a reserved item to the queue with optional retry delay."""
        ...

    async def extend_reservation(self, reservation_id: str, lease_seconds: int) -> bool:
        """Extend the lease for an active reservation."""
        ...

    async def depth(self, topic: str | None = None) -> int:
        """Return queue depth, optionally scoped to a topic."""
        ...


class RetrievalMode(StrEnum):
    """Planner retrieval mode for a step."""

    LEXICAL = "lexical"
    VECTOR = "vector"
    HYBRID = "hybrid"
    FEDERATED = "federated"


@dataclass(frozen=True)
class PlannerTarget:
    """A backend/index target that can serve retrieval."""

    target_id: str
    backend: str
    namespace: str | None = None
    metadata: Metadata = field(default_factory=dict)


@dataclass(frozen=True)
class PlannerRequest:
    """Input request for planner routing decisions."""

    query: str
    tenant_id: str | None = None
    latency_budget_ms: int = 2000
    max_candidates: int = 20
    filters: Metadata = field(default_factory=dict)
    metadata: Metadata = field(default_factory=dict)


@dataclass(frozen=True)
class PlannerStep:
    """A single retrieval/planning step emitted by the planner."""

    step_id: str
    target: PlannerTarget
    mode: RetrievalMode = RetrievalMode.HYBRID
    top_k: int = 10
    timeout_ms: int = 800
    requires: tuple[str, ...] = ()
    filter_overrides: Metadata = field(default_factory=dict)
    metadata: Metadata = field(default_factory=dict)


@dataclass(frozen=True)
class PlannerPlan:
    """Planner output with ordered steps."""

    plan_id: str
    steps: tuple[PlannerStep, ...]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    estimated_cost: float = 0.0
    metadata: Metadata = field(default_factory=dict)


@runtime_checkable
class PlannerContract(Protocol):
    """Query planner/router coordination contract."""

    async def plan(self, request: PlannerRequest) -> PlannerPlan:
        """Generate a routing plan for a query request."""
        ...

    async def replan(
        self,
        request: PlannerRequest,
        *,
        previous_plan: PlannerPlan,
        observations: Metadata | None = None,
    ) -> PlannerPlan:
        """Generate a revised plan after execution feedback."""
        ...


class StorageTier(StrEnum):
    """Storage tier classification for lifecycle policy."""

    HOT = "hot"
    WARM = "warm"
    COLD = "cold"
    ARCHIVE = "archive"


class LifecycleActionType(StrEnum):
    """Lifecycle actions commonly emitted by policy engines."""

    ROLLOVER = "rollover"
    COMPACT = "compact"
    REINDEX = "reindex"
    MOVE_TIER = "move_tier"
    SNAPSHOT = "snapshot"
    DELETE = "delete"


@dataclass(frozen=True)
class LifecycleAsset:
    """Index or shard-like asset tracked by lifecycle policies."""

    asset_id: str
    namespace: str
    tier: StorageTier = StorageTier.HOT
    size_bytes: int = 0
    document_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_accessed_at: datetime | None = None
    metadata: Metadata = field(default_factory=dict)


@dataclass(frozen=True)
class LifecycleAction:
    """A policy action scheduled for a lifecycle asset."""

    action_id: str
    action_type: LifecycleActionType
    asset_id: str
    reason: str
    execute_after: datetime | None = None
    target_tier: StorageTier | None = None
    metadata: Metadata = field(default_factory=dict)


@runtime_checkable
class LifecyclePolicyContract(Protocol):
    """Lifecycle policy contract for index/data transitions."""

    async def evaluate(
        self,
        assets: tuple[LifecycleAsset, ...],
        *,
        now: datetime | None = None,
    ) -> tuple[LifecycleAction, ...]:
        """Evaluate assets and return lifecycle actions to apply."""
        ...

    async def record_outcome(
        self,
        action_id: str,
        *,
        success: bool,
        details: str | None = None,
    ) -> None:
        """Record policy execution outcome for future evaluations."""
        ...
