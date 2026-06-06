"""Tests for AgentCouncil orchestration: concurrency, timeout, abstention, adapter."""

from __future__ import annotations

import asyncio

import pytest

from cemaf.agents.base import AgentContext, AgentResult, AgentState
from cemaf.core.types import AgentID
from cemaf.council.aggregator import DefaultVoteAggregator
from cemaf.council.council import AgentCouncil, create_agent_council
from cemaf.council.types import CouncilConfig, CouncilQuestion, Opinion

Q = CouncilQuestion(prompt="which?", options=("A", "B"))
CTX = AgentContext(run_id="r", agent_id="council")


class _FixedMember:
    def __init__(self, member_id: str, choice: str | None, *, raises: bool = False) -> None:
        self._id = AgentID(member_id)
        self._choice = choice
        self._raises = raises

    @property
    def id(self) -> AgentID:
        return self._id

    async def deliberate(self, *, question: CouncilQuestion, goal: object, context: AgentContext) -> Opinion:
        if self._raises:
            raise RuntimeError("member exploded")
        return Opinion(member_id=self._id, choice=self._choice)


class _BarrierMember:
    """Proves concurrency: every member must reach the barrier or the gather deadlocks."""

    def __init__(self, member_id: str, choice: str, barrier: asyncio.Barrier) -> None:
        self._id = AgentID(member_id)
        self._choice = choice
        self._barrier = barrier

    @property
    def id(self) -> AgentID:
        return self._id

    async def deliberate(self, *, question: CouncilQuestion, goal: object, context: AgentContext) -> Opinion:
        await self._barrier.wait()  # serial execution would hang here forever
        return Opinion(member_id=self._id, choice=self._choice)


@pytest.mark.asyncio
async def test_members_run_concurrently_via_barrier() -> None:
    barrier = asyncio.Barrier(3)
    council = AgentCouncil(
        members=(
            _BarrierMember("m1", "A", barrier),
            _BarrierMember("m2", "A", barrier),
            _BarrierMember("m3", "B", barrier),
        ),
        aggregator=DefaultVoteAggregator(),
    )
    decision = await asyncio.wait_for(council.decide(question=Q, goal={}, context=CTX), timeout=2.0)
    assert decision.winning_choice == "A"


@pytest.mark.asyncio
async def test_raising_member_abstains() -> None:
    council = AgentCouncil(
        members=(_FixedMember("m1", "A"), _FixedMember("m2", "A"), _FixedMember("boom", None, raises=True)),
        aggregator=DefaultVoteAggregator(),
    )
    decision = await council.decide(question=Q, goal={}, context=CTX)
    assert decision.winning_choice == "A"
    boom = next(b for b in decision.ballots if b.member_id == AgentID("boom"))
    assert boom.abstained is True
    assert boom.error is not None and "exploded" in boom.error


@pytest.mark.asyncio
async def test_hung_member_times_out_to_abstention() -> None:
    class _Hang:
        @property
        def id(self) -> AgentID:
            return AgentID("hang")

        async def deliberate(
            self, *, question: CouncilQuestion, goal: object, context: AgentContext
        ) -> Opinion:
            await asyncio.sleep(10)
            return Opinion(member_id=self.id, choice="A")

    from datetime import timedelta

    council = AgentCouncil(
        members=(_FixedMember("m1", "A"), _Hang()),
        aggregator=DefaultVoteAggregator(),
        config=CouncilConfig(member_timeout=timedelta(milliseconds=50)),
    )
    decision = await asyncio.wait_for(council.decide(question=Q, goal={}, context=CTX), timeout=2.0)
    assert decision.winning_choice == "A"
    hang = next(b for b in decision.ballots if b.member_id == AgentID("hang"))
    assert hang.abstained is True


# --- Agent adapter ---------------------------------------------------------


class _ChoiceAgent:
    """A plain Agent whose output is a choice string."""

    def __init__(self, agent_id: str, choice: str, *, ok: bool = True) -> None:
        self._id = AgentID(agent_id)
        self._choice = choice
        self._ok = ok

    @property
    def id(self) -> AgentID:
        return self._id

    @property
    def description(self) -> str:
        return "choice agent"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: object, context: AgentContext) -> AgentResult[str]:
        if not self._ok:
            return AgentResult.fail(error="declined", state=AgentState())
        return AgentResult.ok(output=self._choice, state=AgentState())


@pytest.mark.asyncio
async def test_plain_agents_adapted_into_members() -> None:
    council = create_agent_council(
        members=(_ChoiceAgent("a1", "A"), _ChoiceAgent("a2", "A"), _ChoiceAgent("a3", "B")),
    )
    decision = await council.decide(question=Q, goal={}, context=CTX)
    assert decision.winning_choice == "A"


@pytest.mark.asyncio
async def test_adapter_failed_agent_abstains() -> None:
    council = create_agent_council(
        members=(_ChoiceAgent("a1", "A"), _ChoiceAgent("a2", "x", ok=False)),
    )
    decision = await council.decide(question=Q, goal={}, context=CTX)
    assert decision.winning_choice == "A"
    a2 = next(b for b in decision.ballots if b.member_id == AgentID("a2"))
    assert a2.abstained is True


@pytest.mark.asyncio
async def test_adapter_choice_outside_options_abstains_with_raw() -> None:
    council = create_agent_council(
        members=(_ChoiceAgent("a1", "A"), _ChoiceAgent("a2", "maybe")),  # 'maybe' not in (A,B)
    )
    decision = await council.decide(question=Q, goal={}, context=CTX)
    a2 = next(b for b in decision.ballots if b.member_id == AgentID("a2"))
    assert a2.abstained is True
    assert a2.raw_choice == "maybe"
