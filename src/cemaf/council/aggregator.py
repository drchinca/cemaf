"""DefaultVoteAggregator — deterministic majority/weighted/quorum/unanimous (SPEC-10)."""

from __future__ import annotations

from cemaf.council.types import (
    AggregationMethod,
    Ballot,
    CouncilConfig,
    CouncilDecision,
    CouncilQuestion,
    Opinion,
)

# Float tie tolerance for weighted scores — avoids `==` on summed confidences.
_TIE_TOLERANCE = 1e-9


class DefaultVoteAggregator:
    """Implements all four AggregationMethods. Tie-break: lexically-smallest option.

    Empty non-abstaining set ⇒ winning_choice=None (no division by zero).
    """

    def __init__(self, *, config: CouncilConfig | None = None) -> None:
        self._config = config or CouncilConfig()

    def aggregate(self, *, question: CouncilQuestion, opinions: tuple[Opinion, ...]) -> CouncilDecision:
        ballots = tuple(
            Ballot(
                member_id=o.member_id,
                choice=o.choice,
                confidence=o.confidence,
                abstained=o.abstained,
                # Surface the abstention reason (exception repr / decline note) for provenance.
                error=o.rationale if o.abstained and o.rationale else None,
                raw_choice=o.raw_choice,
                # Carry the member's own reason for the vote into the provenance
                # record, so the audit trail shows WHY each member voted.
                rationale=o.rationale,
            )
            for o in opinions
        )
        # Only non-abstaining opinions with a choice inside the option set count.
        valid_options = set(question.options)
        voting = [
            o for o in opinions if not o.abstained and o.choice is not None and o.choice in valid_options
        ]

        method = self._config.method
        if len(voting) < self._config.min_members:
            return self._no_decision(method=method, ballots=ballots, tally={})

        tally = self._build_tally(method=method, voting=voting)
        if not tally:
            return self._no_decision(method=method, ballots=ballots, tally={})

        winner = self._pick_winner(tally=tally)

        if method is AggregationMethod.QUORUM:
            total = float(len(voting))
            share = tally[winner] / total if total else 0.0
            if share < self._config.quorum_fraction:
                return self._no_decision(method=method, ballots=ballots, tally=tally)
            return CouncilDecision(
                winning_choice=winner, method=method, tally=tally, ballots=ballots, quorum_met=True
            )

        if method is AggregationMethod.UNANIMOUS:
            distinct = {o.choice for o in voting}
            if len(distinct) != 1:
                return self._no_decision(method=method, ballots=ballots, tally=tally)
            return CouncilDecision(
                winning_choice=winner, method=method, tally=tally, ballots=ballots, quorum_met=True
            )

        # MAJORITY / WEIGHTED
        return CouncilDecision(
            winning_choice=winner, method=method, tally=tally, ballots=ballots, quorum_met=True
        )

    def _build_tally(self, *, method: AggregationMethod, voting: list[Opinion]) -> dict[str, float]:
        tally: dict[str, float] = {}
        for o in voting:
            assert o.choice is not None  # filtered above
            increment = o.confidence if method is AggregationMethod.WEIGHTED else 1.0
            tally[o.choice] = tally.get(o.choice, 0.0) + increment
        return tally

    @staticmethod
    def _pick_winner(*, tally: dict[str, float]) -> str:
        """Highest score; ties broken by lexically-smallest option (tolerance on float ties)."""
        best_score = max(tally.values())
        leaders = sorted(c for c, s in tally.items() if abs(s - best_score) <= _TIE_TOLERANCE)
        return leaders[0]

    @staticmethod
    def _no_decision(
        *, method: AggregationMethod, ballots: tuple[Ballot, ...], tally: dict[str, float]
    ) -> CouncilDecision:
        return CouncilDecision(
            winning_choice=None,
            method=method,
            tally=tally,
            ballots=ballots,
            quorum_met=False,
        )
