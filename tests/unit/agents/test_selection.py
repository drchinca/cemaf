"""Contract tests for auction-based agent selection (SPEC-09 §3, §4, §7)."""

from __future__ import annotations

import pytest

from cemaf.agents.base import AgentContext, AgentResult, AgentState
from cemaf.agents.selection import (
    Bid,
    BidContext,
    Capability,
    DefaultAgentSelector,
    read_capabilities,
    read_load,
)
from cemaf.core.types import AgentID


class _Advertiser:
    """Agent implementing CapabilityAdvertiser with configurable caps + load."""

    def __init__(self, agent_id: str, caps: frozenset[Capability], load: float) -> None:
        self._id = AgentID(agent_id)
        self._caps = caps
        self._load = load

    @property
    def id(self) -> AgentID:
        return self._id

    @property
    def description(self) -> str:
        return "advertiser"

    @property
    def skills(self) -> tuple[()]:
        return ()

    @property
    def capabilities(self) -> frozenset[Capability]:
        return self._caps

    @property
    def current_load(self) -> float:
        return self._load

    async def run(self, goal: object, context: AgentContext) -> AgentResult[str]:
        return AgentResult.ok(output="ok", state=AgentState.COMPLETED)


class _Generalist:
    """Agent that does NOT implement CapabilityAdvertiser."""

    def __init__(self, agent_id: str) -> None:
        self._id = AgentID(agent_id)

    @property
    def id(self) -> AgentID:
        return self._id

    @property
    def description(self) -> str:
        return "generalist"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: object, context: AgentContext) -> AgentResult[str]:
        return AgentResult.ok(output="ok", state=AgentState.COMPLETED)


def _ctx(*, cost: float = 0.0, token: float = 0.0) -> BidContext:
    return BidContext(capability=Capability.WRITE, cost_utilization=cost, token_utilization=token)


class TestDefaultSelector:
    def test_deterministic(self) -> None:
        sel = DefaultAgentSelector()
        agents = (_Advertiser("a", frozenset({Capability.WRITE}), 0.2), _Generalist("b"))
        first = sel.select(candidates=agents, bid_context=_ctx())
        second = sel.select(candidates=agents, bid_context=_ctx())
        assert first == second

    def test_capability_match_beats_generalist(self) -> None:
        sel = DefaultAgentSelector()
        winner = sel.select(
            candidates=(_Generalist("gen"), _Advertiser("wr", frozenset({Capability.WRITE}), 0.5)),
            bid_context=_ctx(),
        )
        assert winner is not None
        assert winner.agent_id == AgentID("wr")
        assert winner.capability_match == 1.0

    def test_higher_load_lowers_score(self) -> None:
        sel = DefaultAgentSelector()
        winner = sel.select(
            candidates=(
                _Advertiser("busy", frozenset({Capability.WRITE}), 0.9),
                _Advertiser("idle", frozenset({Capability.WRITE}), 0.1),
            ),
            bid_context=_ctx(),
        )
        assert winner is not None
        assert winner.agent_id == AgentID("idle")

    def test_budget_pressure_preserves_winner(self) -> None:
        sel = DefaultAgentSelector()
        cands = (
            _Advertiser("idle", frozenset({Capability.WRITE}), 0.1),
            _Advertiser("busy", frozenset({Capability.WRITE}), 0.8),
        )
        no_pressure = sel.select(candidates=cands, bid_context=_ctx())
        pressured = sel.select(candidates=cands, bid_context=_ctx(cost=0.95))
        assert no_pressure is not None and pressured is not None
        assert no_pressure.agent_id == pressured.agent_id  # shared term shifts both equally
        assert pressured.score < no_pressure.score

    def test_over_budget_clamps_headroom_to_zero(self) -> None:
        sel = DefaultAgentSelector()
        bid = sel.bid_for(
            agent=_Advertiser("a", frozenset({Capability.WRITE}), 0.0),
            bid_context=_ctx(cost=1.5),
        )
        assert bid.budget_headroom == 0.0
        assert 0.0 <= bid.score <= 1.0

    def test_exact_tie_resolves_by_id(self) -> None:
        sel = DefaultAgentSelector()
        # identical caps + load → identical score; id tie-break, desc → 'z' wins
        winner = sel.select(
            candidates=(
                _Advertiser("a", frozenset({Capability.WRITE}), 0.5),
                _Advertiser("z", frozenset({Capability.WRITE}), 0.5),
            ),
            bid_context=_ctx(),
        )
        assert winner is not None
        assert winner.agent_id == AgentID("z")

    def test_single_candidate_produces_bid(self) -> None:
        sel = DefaultAgentSelector()
        winner = sel.select(
            candidates=(_Advertiser("solo", frozenset({Capability.WRITE}), 0.3),),
            bid_context=_ctx(),
        )
        assert winner is not None
        assert winner.agent_id == AgentID("solo")

    def test_no_candidates_returns_none(self) -> None:
        assert DefaultAgentSelector().select(candidates=(), bid_context=_ctx()) is None


class TestScoringInvariants:
    @pytest.mark.parametrize("load", [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, -0.3])
    @pytest.mark.parametrize("cost", [0.0, 0.5, 1.0, 2.0])
    def test_scores_bounded_zero_to_one(self, load: float, cost: float) -> None:
        sel = DefaultAgentSelector()
        bid = sel.bid_for(
            agent=_Advertiser("a", frozenset({Capability.WRITE}), load),
            bid_context=_ctx(cost=cost),
        )
        for component in (bid.score, bid.capability_match, bid.load_factor, bid.budget_headroom):
            assert 0.0 <= component <= 1.0

    @pytest.mark.parametrize("ids", [("a", "b", "c"), ("c", "b", "a"), ("b", "a", "c"), ("m", "z", "a")])
    def test_winner_independent_of_input_order(self, ids: tuple[str, ...]) -> None:
        """Property 1: same candidate set, any ordering → same winner."""
        sel = DefaultAgentSelector()
        cands = tuple(_Advertiser(i, frozenset({Capability.WRITE}), 0.5) for i in ids)
        winner = sel.select(candidates=cands, bid_context=_ctx())
        assert winner is not None
        # all identical scores → lexicographically-largest id wins regardless of order
        assert winner.agent_id == AgentID(max(ids))


class TestDuckTypedReads:
    def test_read_capabilities_on_advertiser(self) -> None:
        agent = _Advertiser("a", frozenset({Capability.WRITE}), 0.1)
        assert read_capabilities(agent) == frozenset({Capability.WRITE})

    def test_read_capabilities_on_generalist_is_none(self) -> None:
        assert read_capabilities(_Generalist("g")) is None

    def test_read_load_defaults_for_generalist(self) -> None:
        assert read_load(_Generalist("g")) == 0.5

    def test_read_load_clamps(self) -> None:
        assert read_load(_Advertiser("a", frozenset(), 5.0)) == 1.0
        assert read_load(_Advertiser("a", frozenset(), -1.0)) == 0.0

    def test_bid_to_metadata_shape(self) -> None:
        bid = Bid(
            agent_id=AgentID("a"),
            score=0.8,
            capability_match=1.0,
            load_factor=0.9,
            budget_headroom=0.7,
        )
        meta = bid.to_metadata()
        assert meta == {
            "agent_id": "a",
            "score": 0.8,
            "capability_match": 1.0,
            "load_factor": 0.9,
            "budget_headroom": 0.7,
        }
