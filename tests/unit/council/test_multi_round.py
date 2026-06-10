"""Multi-round AgentCouncil: members see prior round opinions and may revise.

Single-round is the ensemble baseline (Wang et al. self-consistency); multi-round
recovers the debate gap (Du et al., MoA) by letting members update on each other.
Tests prove (a) round 2+ sees prior opinions in agent_context.global_memory, (b)
a swing-voter changes the verdict, (c) tally-unchanged early-stops, (d) default
rounds=1 is byte-identical to before.
"""

from __future__ import annotations

import pytest

from cemaf.agents.base import AgentContext
from cemaf.core.types import AgentID
from cemaf.council.aggregator import DefaultVoteAggregator
from cemaf.council.council import AgentCouncil
from cemaf.council.types import (
    AggregationMethod,
    CouncilConfig,
    CouncilQuestion,
    Opinion,
)
from cemaf.interceptors.types import COUNCIL_PRIOR_ROUND_KEY

Q = CouncilQuestion(prompt="ship?", options=("ship", "hold"))
CTX = AgentContext(run_id="r", agent_id="council")


class _ScriptedMember:
    """Member that yields one Opinion per round; records what it saw each call.

    Real production members are LLMs that read prior_round and revise; this
    deterministic stand-in lets us verify the broadcast plumbing without flake.
    """

    def __init__(self, member_id: str, choices: list[str]) -> None:
        self._id = AgentID(member_id)
        self._choices = list(choices)
        self.seen: list[list[dict[str, object]]] = []  # one entry per round

    @property
    def id(self) -> AgentID:
        return self._id

    async def deliberate(self, *, question: CouncilQuestion, goal: object, context: AgentContext) -> Opinion:
        prior = context.global_memory.get(COUNCIL_PRIOR_ROUND_KEY, [])
        self.seen.append(list(prior) if isinstance(prior, list) else [])
        choice = self._choices.pop(0) if self._choices else None
        return Opinion(member_id=self._id, choice=choice)


class TestMultiRoundBroadcast:
    @pytest.mark.asyncio
    async def test_round_one_sees_no_prior(self) -> None:
        m = _ScriptedMember("a", ["ship"])
        council = AgentCouncil(
            members=(m,),
            aggregator=DefaultVoteAggregator(),
            config=CouncilConfig(rounds=1),
        )
        await council.decide(question=Q, goal={}, context=CTX)
        assert m.seen == [[]]  # one round, empty prior

    @pytest.mark.asyncio
    async def test_round_two_sees_round_one_opinions(self) -> None:
        # Three members: a + b vote ship, c votes hold (round 1: 2-1 ship).
        # Same in round 2 — but proves the broadcast surface to members.
        a = _ScriptedMember("a", ["ship", "ship"])
        b = _ScriptedMember("b", ["ship", "ship"])
        c = _ScriptedMember("c", ["hold", "hold"])
        council = AgentCouncil(
            members=(a, b, c),
            aggregator=DefaultVoteAggregator(),
            config=CouncilConfig(rounds=2),
        )
        decision = await council.decide(question=Q, goal={}, context=CTX)
        assert decision.winning_choice == "ship"
        # Round 2's prior carries all 3 round-1 opinions for every member.
        for member in (a, b, c):
            assert len(member.seen) == 2
            assert member.seen[0] == []  # round 1: no prior
            assert len(member.seen[1]) == 3  # round 2: saw all 3 votes
            ids = {o["member_id"] for o in member.seen[1]}
            assert ids == {"a", "b", "c"}

    @pytest.mark.asyncio
    async def test_swing_voter_flips_verdict_in_round_two(self) -> None:
        """Round 1: 2-1 ship; swing voter sees the vote and switches → 2-1 hold."""

        class _Swing:
            def __init__(self) -> None:
                self._id = AgentID("swing")
                self._round = 0

            @property
            def id(self) -> AgentID:
                return self._id

            async def deliberate(
                self, *, question: CouncilQuestion, goal: object, context: AgentContext
            ) -> Opinion:
                self._round += 1
                # Round 1: vote with the "obvious" answer.
                if self._round == 1:
                    return Opinion(member_id=self._id, choice="ship")
                # Round 2: see peers, decide they're wrong, switch to hold.
                return Opinion(member_id=self._id, choice="hold")

        # In round 2: holder + swing-now-hold = 2 vs ship = 1 → "hold" wins.
        ship_voter = _ScriptedMember("ship_only", ["ship", "ship"])
        holder = _ScriptedMember("holder", ["hold", "hold"])
        swing = _Swing()
        council = AgentCouncil(
            members=(ship_voter, holder, swing),
            aggregator=DefaultVoteAggregator(),
            config=CouncilConfig(rounds=2),
        )

        decision = await council.decide(question=Q, goal={}, context=CTX)
        assert decision.winning_choice == "hold"
        assert decision.tally == {"ship": 1.0, "hold": 2.0}


class TestEarlyStop:
    @pytest.mark.asyncio
    async def test_unchanged_tally_stops_early(self) -> None:
        """If round 2 produces the same tally as round 1, no round 3 fires."""
        a = _ScriptedMember("a", ["ship", "ship", "ship"])
        b = _ScriptedMember("b", ["ship", "ship", "ship"])
        c = _ScriptedMember("c", ["hold", "hold", "hold"])
        council = AgentCouncil(
            members=(a, b, c),
            aggregator=DefaultVoteAggregator(),
            config=CouncilConfig(rounds=5),
        )
        decision = await council.decide(question=Q, goal={}, context=CTX)
        assert decision.winning_choice == "ship"
        # Each member ran exactly twice (round 1, round 2 — then stopped).
        assert len(a.seen) == 2
        assert len(b.seen) == 2
        assert len(c.seen) == 2

    @pytest.mark.asyncio
    async def test_changing_tally_continues_to_max_rounds(self) -> None:
        """A council that keeps changing its mind runs the full rounds budget."""
        # Each member alternates per round; tally is always different from prior.
        a = _ScriptedMember("a", ["ship", "hold", "ship"])
        b = _ScriptedMember("b", ["ship", "hold", "ship"])
        council = AgentCouncil(
            members=(a, b),
            aggregator=DefaultVoteAggregator(),
            config=CouncilConfig(rounds=3),
        )
        await council.decide(question=Q, goal={}, context=CTX)
        # Both members ran the full 3 rounds — no early-stop.
        assert len(a.seen) == 3
        assert len(b.seen) == 3


class TestBackwardsCompatibility:
    @pytest.mark.asyncio
    async def test_default_rounds_is_one_and_unchanged(self) -> None:
        """rounds=1 (default) is exactly the prior single-round behaviour."""
        a = _ScriptedMember("a", ["ship"])
        b = _ScriptedMember("b", ["ship"])
        c = _ScriptedMember("c", ["hold"])
        council = AgentCouncil(members=(a, b, c), aggregator=DefaultVoteAggregator())
        # config defaults to rounds=1; no broadcast key in member context.
        decision = await council.decide(question=Q, goal={}, context=CTX)
        assert decision.winning_choice == "ship"
        for m in (a, b, c):
            assert m.seen == [[]]

    def test_rounds_zero_rejected(self) -> None:
        with pytest.raises(ValueError, match="rounds must be >= 1"):
            CouncilConfig(rounds=0)


class TestDeliberationCost:
    @pytest.mark.asyncio
    async def test_each_round_uses_same_method(self) -> None:
        """Multi-round respects the aggregator's method on every round."""
        a = _ScriptedMember("a", ["ship", "ship"])
        b = _ScriptedMember("b", ["hold", "hold"])
        # Both council config (round semantics) and aggregator config (method)
        # need UNANIMOUS — they're independent knobs by design.
        unanimous_cfg = CouncilConfig(method=AggregationMethod.UNANIMOUS, rounds=2)
        council = AgentCouncil(
            members=(a, b),
            aggregator=DefaultVoteAggregator(config=unanimous_cfg),
            config=unanimous_cfg,
        )
        decision = await council.decide(question=Q, goal={}, context=CTX)
        # Disagreement under UNANIMOUS → no decision (consistent both rounds).
        assert decision.winning_choice is None
