"""Contract tests for the NIAH benchmark schema and aggregator.

Pure offline — no LLM, no I/O. Pins the SPEC-11 §3 Invariants the harness ships on.
"""

from __future__ import annotations

import math

import pytest

from benchmarks.niah.aggregate import aggregate_arm_tier, build_scaling_curves
from benchmarks.niah.schema import (
    Arm,
    HaystackTier,
    QuestionRun,
    headline_metric,
)


def _tier(label: str = "10MB", size: int = 10 * 1024 * 1024, docs: int = 100) -> HaystackTier:
    return HaystackTier(label=label, size_bytes=size, doc_count=docs)


def _run(
    *,
    arm: Arm = Arm.CEMAF_FULL,
    tier: HaystackTier | None = None,
    judged: bool = True,
    cited: bool = True,
    error: str | None = None,
    rep: int = 0,
    qid: str = "q0",
) -> QuestionRun:
    return QuestionRun(
        question_id=qid,
        arm=arm,
        tier=tier or _tier(),
        rep=rep,
        compiled_tokens=1024,
        compile_ms=50,
        answer_ms=200,
        cost_usd=0.001,
        answer_text="answer",
        judged_correct=judged,
        citation_grounded=cited,
        error=error,
    )


# --- §3 Invariant 4: headline metric is correct AND citation-grounded ------------------


def test_headline_requires_both_correct_and_grounded() -> None:
    assert headline_metric(run=_run(judged=True, cited=True)) is True
    assert headline_metric(run=_run(judged=True, cited=False)) is False  # memorization defended
    assert headline_metric(run=_run(judged=False, cited=True)) is False
    assert headline_metric(run=_run(judged=False, cited=False)) is False


# --- §3 Invariant 6: errors surface, never silently dropped ---------------------------


def test_errored_runs_count_as_failures_in_aggregate() -> None:
    runs = (
        _run(qid="q0", judged=True, cited=True),
        _run(qid="q1", judged=True, cited=True),
        _run(qid="q2", error="OOM", judged=False, cited=False),
    )
    agg = aggregate_arm_tier(runs=runs)
    assert agg.n == 3  # the errored run is INCLUDED, not dropped
    assert agg.correctness_rate == pytest.approx(2 / 3)


# --- aggregation correctness ----------------------------------------------------------


def test_correctness_rate_uses_headline_metric_not_judged_alone() -> None:
    # 3 judged-correct, but 1 of them isn't grounded -> headline rate = 2/3, not 3/3.
    runs = (
        _run(qid="q0", judged=True, cited=True),
        _run(qid="q1", judged=True, cited=True),
        _run(qid="q2", judged=True, cited=False),
    )
    agg = aggregate_arm_tier(runs=runs)
    assert agg.correctness_rate == pytest.approx(2 / 3)


def test_stderr_is_binomial_proportion_approximation() -> None:
    runs = tuple(_run(qid=f"q{i}", judged=(i % 2 == 0), cited=(i % 2 == 0)) for i in range(10))
    agg = aggregate_arm_tier(runs=runs)
    expected_se = math.sqrt(0.5 * 0.5 / 10)
    assert agg.correctness_stderr == pytest.approx(expected_se)


def test_aggregate_rejects_mixed_arm_or_tier() -> None:
    runs = (
        _run(arm=Arm.CEMAF_FULL),
        _run(arm=Arm.NAIVE_DUMP),
    )
    with pytest.raises(ValueError, match="uniform"):
        aggregate_arm_tier(runs=runs)


def test_aggregate_rejects_empty_runs() -> None:
    with pytest.raises(ValueError, match="at least one run"):
        aggregate_arm_tier(runs=())


# --- scaling curve groups by arm and orders by size ---------------------------------


def test_scaling_curve_orders_points_by_size_ascending() -> None:
    t10 = _tier("10MB", 10 * 1024 * 1024)
    t100 = _tier("100MB", 100 * 1024 * 1024)
    t1g = _tier("1GB", 1024 * 1024 * 1024)
    runs = (
        _run(tier=t1g, qid="a"),
        _run(tier=t10, qid="b"),
        _run(tier=t100, qid="c"),
    )
    curves = build_scaling_curves(runs=runs)
    assert len(curves) == 1
    point_sizes = [p.tier.size_bytes for p in curves[0].points]
    assert point_sizes == sorted(point_sizes)


def test_scaling_curves_one_per_arm() -> None:
    t10 = _tier()
    runs = (
        _run(arm=Arm.CEMAF_FULL, tier=t10, qid="a"),
        _run(arm=Arm.CEMAF_NO_KG, tier=t10, qid="b"),
        _run(arm=Arm.NAIVE_DUMP, tier=t10, qid="c"),
    )
    curves = build_scaling_curves(runs=runs)
    arms = {curve.arm for curve in curves}
    assert arms == {Arm.CEMAF_FULL, Arm.CEMAF_NO_KG, Arm.NAIVE_DUMP}
