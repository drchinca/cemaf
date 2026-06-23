"""Tests for orchestration control-plane contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cemaf.orchestration.contracts import (
    LifecycleAction,
    LifecycleActionType,
    LifecycleAsset,
    LifecyclePolicyContract,
    PlannerContract,
    PlannerPlan,
    PlannerRequest,
    PlannerStep,
    PlannerTarget,
    QueueContract,
    QueueItem,
    QueueReservation,
    RetrievalMode,
    StorageTier,
)


class _QueueImpl:
    async def enqueue(self, item: QueueItem) -> str:
        return item.item_id

    async def reserve(
        self,
        *,
        worker_id: str,
        max_items: int = 1,
        lease_seconds: int = 30,
        topics: tuple[str, ...] = (),
    ) -> tuple[QueueReservation, ...]:
        return ()

    async def complete(self, reservation_id: str) -> bool:
        return True

    async def retry(
        self,
        reservation_id: str,
        *,
        delay_seconds: int = 0,
        error: str | None = None,
    ) -> bool:
        return True

    async def extend_reservation(self, reservation_id: str, lease_seconds: int) -> bool:
        return True

    async def depth(self, topic: str | None = None) -> int:
        return 0


class _PlannerImpl:
    async def plan(self, request: PlannerRequest) -> PlannerPlan:
        return PlannerPlan(plan_id="p1", steps=())

    async def replan(
        self,
        request: PlannerRequest,
        *,
        previous_plan: PlannerPlan,
        observations: dict[str, object] | None = None,
    ) -> PlannerPlan:
        return previous_plan


class _LifecycleImpl:
    async def evaluate(
        self,
        assets: tuple[LifecycleAsset, ...],
        *,
        now: datetime | None = None,
    ) -> tuple[LifecycleAction, ...]:
        return ()

    async def record_outcome(
        self,
        action_id: str,
        *,
        success: bool,
        details: str | None = None,
    ) -> None:
        return None


class TestQueueContract:
    def test_queue_item_defaults(self) -> None:
        item = QueueItem(item_id="q-1", topic="default", payload={"x": 1})
        assert item.priority == 0
        assert item.delivery_attempt == 0
        assert item.enqueued_at.tzinfo == UTC
        assert item.metadata == {}

    def test_queue_reservation_expiry(self) -> None:
        item = QueueItem(item_id="q-1", topic="default", payload={})
        reservation = QueueReservation(
            reservation_id="r-1",
            item=item,
            worker_id="worker-a",
            leased_until=datetime.now(UTC) - timedelta(seconds=1),
        )
        assert reservation.is_expired is True

    def test_runtime_protocol_check(self) -> None:
        assert isinstance(_QueueImpl(), QueueContract)


class TestPlannerContract:
    def test_plan_primitives(self) -> None:
        target = PlannerTarget(target_id="idx-a", backend="qdrant", namespace="tenant-1")
        step = PlannerStep(
            step_id="s1",
            target=target,
            mode=RetrievalMode.HYBRID,
            top_k=25,
            timeout_ms=500,
        )
        plan = PlannerPlan(plan_id="p1", steps=(step,))

        assert plan.steps[0].target.backend == "qdrant"
        assert plan.steps[0].mode == RetrievalMode.HYBRID

    def test_runtime_protocol_check(self) -> None:
        assert isinstance(_PlannerImpl(), PlannerContract)


class TestLifecyclePolicyContract:
    def test_lifecycle_primitives(self) -> None:
        asset = LifecycleAsset(
            asset_id="idx-1",
            namespace="tenant-1",
            tier=StorageTier.WARM,
            size_bytes=1024,
        )
        action = LifecycleAction(
            action_id="a-1",
            action_type=LifecycleActionType.MOVE_TIER,
            asset_id=asset.asset_id,
            reason="cooling-policy",
            target_tier=StorageTier.COLD,
        )

        assert action.asset_id == "idx-1"
        assert action.target_tier == StorageTier.COLD

    def test_runtime_protocol_check(self) -> None:
        assert isinstance(_LifecycleImpl(), LifecyclePolicyContract)
