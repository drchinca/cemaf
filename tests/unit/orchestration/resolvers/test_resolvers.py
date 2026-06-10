"""Contract tests for NodeResolver — the dispatch seam.

Each resolver answers ONE question: given a node + context, what's the next step?
The contract is observable here without spinning up the full executor.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from cemaf.agents.base import AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.agents.selection import Capability, DefaultAgentSelector
from cemaf.core.types import AgentID
from cemaf.council.types import Opinion
from cemaf.orchestration.dag import Node
from cemaf.orchestration.resolvers import (
    AuctionResolver,
    CouncilResolver,
    NodeComplete,
    RunAgent,
    StaticRefResolver,
)

# --- Test fakes ------------------------------------------------------------


class _PlanGoal(BaseModel):
    objective: str = "x"


class _Voter:
    """A full agent that also deliberates — for council resolver."""

    def __init__(self, name: str, vote: str) -> None:
        self._id, self._vote = AgentID(name), vote

    @property
    def id(self) -> AgentID:
        return self._id

    @property
    def description(self) -> str:
        return "voter"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _PlanGoal, context: AgentContext) -> AgentResult[str]:
        return AgentResult.ok(output=self._vote, state=AgentState())

    async def deliberate(self, *, question: object, goal: object, context: AgentContext) -> Opinion:
        return Opinion(member_id=self._id, choice=self._vote)


class _Worker:
    """A WRITE-capable agent for the auction resolver."""

    def __init__(self, name: str, load: float) -> None:
        self._id, self._load = AgentID(name), load

    @property
    def id(self) -> AgentID:
        return self._id

    @property
    def description(self) -> str:
        return "worker"

    @property
    def skills(self) -> tuple[()]:
        return ()

    @property
    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.WRITE})

    @property
    def current_load(self) -> float:
        return self._load

    async def run(self, goal: _PlanGoal, context: AgentContext) -> AgentResult[str]:
        return AgentResult.ok(output=str(self._id), state=AgentState())


# --- StaticRefResolver -----------------------------------------------------


class TestStaticRefResolver:
    @pytest.mark.asyncio
    async def test_always_matches_and_returns_ref_id(self) -> None:
        resolver = StaticRefResolver()
        node = Node.agent(id="n", name="n", agent_id="Writer")
        assert resolver.matches(node=node) is True

        outcome = await resolver.resolve(node=node, resolved_inputs={}, run_id="r", start=0.0)
        assert isinstance(outcome, RunAgent)
        assert outcome.agent_name == "Writer"
        assert outcome.bid_metadata is None

    @pytest.mark.asyncio
    async def test_empty_ref_id_is_passed_through(self) -> None:
        # The executor handles the 'no ref_id' error; the resolver itself doesn't validate.
        resolver = StaticRefResolver()
        node = Node.auction(id="n", name="n", capability=Capability.WRITE.value)
        outcome = await resolver.resolve(node=node, resolved_inputs={}, run_id="r", start=0.0)
        assert isinstance(outcome, RunAgent)
        assert outcome.agent_name == ""


# --- AuctionResolver -------------------------------------------------------


class TestAuctionResolver:
    def _registry(self) -> AgentRegistry:
        reg = AgentRegistry()
        reg.register_agent(
            agent_instance=_Worker("WriterBusy", 0.9),
            goal_type=_PlanGoal,
            capabilities=frozenset({Capability.WRITE}),
        )
        reg.register_agent(
            agent_instance=_Worker("WriterIdle", 0.1),
            goal_type=_PlanGoal,
            capabilities=frozenset({Capability.WRITE}),
        )
        return reg

    def test_matches_only_when_capability_set(self) -> None:
        resolver = AuctionResolver(registry=self._registry(), selector=DefaultAgentSelector())
        assert resolver.matches(node=Node.auction(id="n", name="n", capability="write")) is True
        assert resolver.matches(node=Node.agent(id="n", name="n", agent_id="X")) is False

    @pytest.mark.asyncio
    async def test_picks_low_load_winner_and_carries_bid_metadata(self) -> None:
        resolver = AuctionResolver(registry=self._registry(), selector=DefaultAgentSelector())
        node = Node.auction(id="n", name="n", capability=Capability.WRITE.value)

        outcome = await resolver.resolve(node=node, resolved_inputs={}, run_id="r", start=0.0)

        assert isinstance(outcome, RunAgent)
        assert outcome.agent_name == "WriterIdle"
        assert outcome.bid_metadata is not None
        assert outcome.bid_metadata["agent_id"] == "WriterIdle"

    @pytest.mark.asyncio
    async def test_no_candidates_falls_through_to_ref_id(self) -> None:
        # capability has no registered candidates → resolver must fall through.
        reg = self._registry()
        resolver = AuctionResolver(registry=reg, selector=DefaultAgentSelector())
        # Node declares a capability with no candidates AND a ref_id fallback.
        node = Node(
            id="n",  # type: ignore[arg-type]
            type=Node.agent(id="x", name="x", agent_id="y").type,
            name="n",
            ref_id="WriterBusy",
            config={"capability": Capability.RESEARCH.value},  # no RESEARCH agents
        )
        outcome = await resolver.resolve(node=node, resolved_inputs={}, run_id="r", start=0.0)
        assert isinstance(outcome, RunAgent)
        assert outcome.agent_name == "WriterBusy"  # fell through to ref_id
        assert outcome.bid_metadata is None


# --- CouncilResolver -------------------------------------------------------


class TestCouncilResolver:
    def _registry_with_votes(self) -> AgentRegistry:
        reg = AgentRegistry()
        for name, vote in (("alice", "ship"), ("bob", "ship"), ("carol", "hold")):
            reg.register_instance(item=_Voter(name, vote))
        return reg

    def test_matches_only_when_council_config_present(self) -> None:
        resolver = CouncilResolver(registry=AgentRegistry())
        ok = Node.council(
            id="n",
            name="n",
            members=("a", "b"),
            options=("x", "y"),
        )
        assert resolver.matches(node=ok) is True
        assert resolver.matches(node=Node.agent(id="x", name="x", agent_id="X")) is False

    @pytest.mark.asyncio
    async def test_resolves_with_winning_choice_as_output(self) -> None:
        resolver = CouncilResolver(registry=self._registry_with_votes())
        node = Node.council(
            id="vote",
            name="vote",
            members=("alice", "bob", "carol"),
            options=("ship", "hold"),
        )
        outcome = await resolver.resolve(node=node, resolved_inputs={}, run_id="r", start=0.0)
        assert isinstance(outcome, NodeComplete)
        assert outcome.result.success is True
        assert outcome.result.output == "ship"  # 2-1 majority
        assert outcome.result.metadata["council"]["winning_choice"] == "ship"

    @pytest.mark.asyncio
    async def test_no_members_returns_failed_node_complete(self) -> None:
        resolver = CouncilResolver(registry=AgentRegistry())
        node = Node.council(
            id="n",
            name="n",
            members=("missing",),
            options=("x", "y"),
        )
        outcome = await resolver.resolve(node=node, resolved_inputs={}, run_id="r", start=0.0)
        # NodeComplete with a failed result — the executor returns this as-is.
        assert isinstance(outcome, NodeComplete)
        assert outcome.result.success is False
        assert "CouncilMember" in (outcome.result.error or "")
