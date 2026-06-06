"""Contract tests for DefaultVoteAggregator (SPEC-10 §3, §4, §7)."""

from __future__ import annotations

import pytest

from cemaf.core.types import AgentID
from cemaf.council.aggregator import DefaultVoteAggregator
from cemaf.council.types import (
    AggregationMethod,
    CouncilConfig,
    CouncilQuestion,
    Opinion,
)

Q = CouncilQuestion(prompt="which?", options=("A", "B", "C", "D"))


def _op(member: str, choice: str | None, *, conf: float = 1.0, abstain: bool = False) -> Opinion:
    return Opinion(member_id=AgentID(member), choice=choice, confidence=conf, abstained=abstain)


def _agg(method: AggregationMethod, **kw: object) -> DefaultVoteAggregator:
    return DefaultVoteAggregator(config=CouncilConfig(method=method, **kw))  # type: ignore[arg-type]


class TestMajority:
    def test_majority_decides(self) -> None:
        d = _agg(AggregationMethod.MAJORITY).aggregate(
            question=Q, opinions=(_op("m1", "A"), _op("m2", "A"), _op("m3", "B"))
        )
        assert d.winning_choice == "A"
        assert d.tally == {"A": 2.0, "B": 1.0}
        assert d.decided is True

    def test_tie_break_is_lexical_not_insertion_order(self) -> None:
        # first member votes B, second votes A — insertion order would yield B
        d = _agg(AggregationMethod.MAJORITY).aggregate(question=Q, opinions=(_op("m1", "B"), _op("m2", "A")))
        assert d.winning_choice == "A"


class TestWeighted:
    def test_weighted_overrides_count(self) -> None:
        d = _agg(AggregationMethod.WEIGHTED).aggregate(
            question=Q,
            opinions=(_op("m1", "A", conf=0.3), _op("m2", "A", conf=0.3), _op("m3", "B", conf=0.9)),
        )
        assert d.winning_choice == "B"

    def test_weighted_exact_tie_breaks_lexically(self) -> None:
        d = _agg(AggregationMethod.WEIGHTED).aggregate(
            question=Q, opinions=(_op("m1", "B", conf=0.5), _op("m2", "A", conf=0.5))
        )
        assert d.winning_choice == "A"


class TestQuorum:
    def test_quorum_not_met_is_no_decision(self) -> None:
        d = _agg(AggregationMethod.QUORUM, quorum_fraction=0.5).aggregate(
            question=Q, opinions=(_op("m1", "A"), _op("m2", "B"), _op("m3", "C"), _op("m4", "D"))
        )
        assert d.winning_choice is None
        assert d.decided is False
        assert d.quorum_met is False

    def test_quorum_met(self) -> None:
        d = _agg(AggregationMethod.QUORUM, quorum_fraction=0.5).aggregate(
            question=Q, opinions=(_op("m1", "A"), _op("m2", "A"), _op("m3", "B"))
        )
        assert d.winning_choice == "A"  # 2/3 >= 0.5
        assert d.quorum_met is True


class TestUnanimous:
    def test_unanimous_agreement(self) -> None:
        d = _agg(AggregationMethod.UNANIMOUS).aggregate(question=Q, opinions=(_op("m1", "A"), _op("m2", "A")))
        assert d.winning_choice == "A"

    def test_unanimous_broken_by_dissent(self) -> None:
        d = _agg(AggregationMethod.UNANIMOUS).aggregate(
            question=Q, opinions=(_op("m1", "A"), _op("m2", "A"), _op("m3", "B"))
        )
        assert d.winning_choice is None


class TestEdgeCases:
    @pytest.mark.parametrize(
        "method",
        list(AggregationMethod),
    )
    def test_all_abstain_no_division_by_zero(self, method: AggregationMethod) -> None:
        d = _agg(method).aggregate(
            question=Q,
            opinions=tuple(_op(f"m{i}", None, abstain=True) for i in range(3)),
        )
        assert d.winning_choice is None
        assert d.tally == {}
        assert d.quorum_met is False
        assert len(d.ballots) == 3  # provenance preserved

    def test_choice_outside_options_is_ignored(self) -> None:
        d = _agg(AggregationMethod.MAJORITY).aggregate(
            question=Q,
            opinions=(_op("m1", "A"), _op("m2", "ZZZ")),  # ZZZ not in options
        )
        assert d.winning_choice == "A"
        assert "ZZZ" not in d.tally

    def test_below_min_members_no_decision(self) -> None:
        d = _agg(AggregationMethod.MAJORITY, min_members=3).aggregate(
            question=Q, opinions=(_op("m1", "A"), _op("m2", "A"))
        )
        assert d.winning_choice is None

    def test_confidence_clamped_at_construction(self) -> None:
        assert _op("m", "A", conf=5.0).confidence == 1.0
        assert _op("m", "A", conf=-2.0).confidence == 0.0

    def test_nan_inf_confidence_sanitized_to_zero(self) -> None:
        assert _op("m", "A", conf=float("nan")).confidence == 0.0
        assert _op("m", "A", conf=float("inf")).confidence == 0.0
        assert _op("m", "A", conf=float("-inf")).confidence == 0.0

    def test_weighted_winner_unaffected_by_nan_member(self) -> None:
        """A member reporting NaN confidence must not corrupt the weighted tally."""
        d = _agg(AggregationMethod.WEIGHTED).aggregate(
            question=Q,
            opinions=(_op("m1", "A", conf=0.6), _op("m2", "B", conf=float("nan"))),
        )
        assert d.winning_choice == "A"  # B's NaN → 0.0, A's 0.6 wins
        assert d.tally["B"] == 0.0

    def test_weighted_tolerance_tie_breaks_lexically(self) -> None:
        """0.1*3 != 0.3 in float; a near-tie within tolerance must still break lexically."""
        d = _agg(AggregationMethod.WEIGHTED).aggregate(
            question=Q,
            opinions=(
                _op("m1", "B", conf=0.1),
                _op("m2", "B", conf=0.1),
                _op("m3", "B", conf=0.1),  # B = 0.1+0.1+0.1 = 0.30000000000000004
                _op("m4", "A", conf=0.3),  # A = 0.3
            ),
        )
        assert d.winning_choice == "A"  # tie within tolerance → lexical 'A'

    def test_failed_member_abstains_council_still_decides(self) -> None:
        d = _agg(AggregationMethod.MAJORITY).aggregate(
            question=Q,
            opinions=(_op("m1", "A"), _op("m2", "A"), _op("m3", None, abstain=True)),
        )
        assert d.winning_choice == "A"
        abstainers = [b for b in d.ballots if b.abstained]
        assert len(abstainers) == 1


class TestDeterminism:
    @pytest.mark.parametrize(
        "order",
        [("A", "B", "C"), ("C", "B", "A"), ("B", "C", "A")],
    )
    def test_permutation_invariant(self, order: tuple[str, ...]) -> None:
        """Property 1: same opinion set, any ordering → same decision."""
        ops = tuple(_op(f"m{i}", c) for i, c in enumerate(order))
        # all distinct single votes → tie at 1.0 each → lexical winner 'A' regardless of order
        d = _agg(AggregationMethod.MAJORITY).aggregate(question=Q, opinions=ops)
        assert d.winning_choice == "A"

    def test_to_metadata_shape(self) -> None:
        d = _agg(AggregationMethod.MAJORITY).aggregate(question=Q, opinions=(_op("m1", "A"),))
        meta = d.to_metadata()
        assert set(meta) == {"winning_choice", "method", "decided", "quorum_met", "tally", "ballots"}
        assert meta["winning_choice"] == "A"
        assert isinstance(meta["ballots"], list)
