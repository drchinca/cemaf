"""SPEC-12 — unit tests for the run-scoped CollisionCoordinator."""

import asyncio

import pytest

from cemaf.collision import (
    AdvisoryLevel,
    AgentWriteSet,
    CollisionCoordinator,
    WriteItem,
    create_collision_coordinator,
)


def _ws(agent_id: str, *paths: str, started_at: float = 0.0) -> AgentWriteSet:
    return AgentWriteSet(
        agent_id=agent_id,
        items=tuple(WriteItem(path=p) for p in paths),
        started_at=started_at,
    )


class TestCollisionCoordinator:
    @pytest.mark.asyncio
    async def test_clear_when_alone(self) -> None:
        coord = CollisionCoordinator()
        await coord.register(_ws("a", "draft.body"))
        adv = await coord.advise_against_cohort("a")
        assert adv.level is AdvisoryLevel.CLEAR

    @pytest.mark.asyncio
    async def test_unknown_agent_is_clear(self) -> None:
        coord = CollisionCoordinator()
        adv = await coord.advise_against_cohort("ghost")
        assert adv.level is AdvisoryLevel.CLEAR

    @pytest.mark.asyncio
    async def test_resolution_between_two_registered_agents(self) -> None:
        coord = CollisionCoordinator()
        await coord.register(_ws("a", "draft.body", started_at=1.0))
        await coord.register(_ws("b", "draft.body", started_at=2.0))
        adv = await coord.advise_against_cohort("a")
        assert adv.level is AdvisoryLevel.RESOLUTION_ADVISORY
        # earlier start (a) holds; b steers
        assert adv.hold == "a"
        assert adv.steer == "b"

    @pytest.mark.asyncio
    async def test_worst_advisory_across_multiple_peers(self) -> None:
        coord = CollisionCoordinator()
        await coord.register(_ws("a", "draft.body", started_at=1.0))
        await coord.register(_ws("b", "research.findings"))  # disjoint → clear
        await coord.register(_ws("c", "draft.body", started_at=2.0))  # identical → resolution
        adv = await coord.advise_against_cohort("a")
        assert adv.level is AdvisoryLevel.RESOLUTION_ADVISORY
        # The winning advisory is against the colliding peer c, not the disjoint b.
        assert {adv.hold, adv.steer} == {"a", "c"}
        assert adv.hold == "a"  # earlier start holds

    @pytest.mark.asyncio
    async def test_advise_against_cohort_is_deterministic(self) -> None:
        coord = CollisionCoordinator()
        await coord.register(_ws("a", "draft.body", started_at=1.0))
        await coord.register(_ws("b", "draft.body", started_at=2.0))
        first = await coord.advise_against_cohort("a")
        second = await coord.advise_against_cohort("a")
        assert first == second

    @pytest.mark.asyncio
    async def test_cohort_timeout_degrades_gracefully(self) -> None:
        """A missing cohort member must not deadlock — bounded wait degrades to registered peers."""
        coord = CollisionCoordinator(cohort_size=3, cohort_timeout_s=0.05)
        await coord.register(_ws("a", "draft.body", started_at=1.0))
        await coord.register(_ws("b", "draft.body", started_at=2.0))
        # third agent never registers; should return after timeout, not hang
        adv = await asyncio.wait_for(coord.advise_against_cohort("a"), timeout=1.0)
        assert adv.level is AdvisoryLevel.RESOLUTION_ADVISORY

    @pytest.mark.asyncio
    async def test_cohort_barrier_blocks_until_quorum(self) -> None:
        """Inv 8 — advise_against_cohort does not return before cohort_size registrations."""
        coord = create_collision_coordinator(cohort_size=2)
        await coord.register(_ws("a", "draft.body"))

        task = asyncio.create_task(coord.advise_against_cohort("a"))
        await asyncio.sleep(0.02)
        assert not task.done()  # still waiting for the second registration

        await coord.register(_ws("b", "draft.body"))
        adv = await asyncio.wait_for(task, timeout=1.0)
        assert adv.level is AdvisoryLevel.RESOLUTION_ADVISORY

    @pytest.mark.asyncio
    async def test_concurrent_registration_is_safe(self) -> None:
        coord = CollisionCoordinator()
        await asyncio.gather(*(coord.register(_ws(f"agent_{i}", "draft.body")) for i in range(10)))
        adv = await coord.advise_against_cohort("agent_0")
        assert adv.level is AdvisoryLevel.RESOLUTION_ADVISORY

    def test_invalid_cohort_size_rejected(self) -> None:
        with pytest.raises(ValueError):
            CollisionCoordinator(cohort_size=0)
