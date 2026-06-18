"""Pure aggregation: QuestionRun list → ArmAggregate / ScalingCurve.

Stays out of any I/O so the headline-metric and standard-error math can be tested offline.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable

from benchmarks.niah.schema import (
    Arm,
    ArmAggregate,
    HaystackTier,
    QuestionRun,
    ScalingCurve,
    headline_metric,
)


def aggregate_arm_tier(*, runs: tuple[QuestionRun, ...]) -> ArmAggregate:
    """Roll up every run for one (arm, tier) into a single aggregate.

    Errors are NOT dropped (SPEC-11 §3 Invariant 6) — they count as failed runs in the
    correctness rate. Standard error uses the binomial proportion approximation.
    """
    if not runs:
        raise ValueError("aggregate_arm_tier requires at least one run")
    arm = runs[0].arm
    tier = runs[0].tier
    if any(r.arm != arm or r.tier != tier for r in runs):
        raise ValueError("aggregate_arm_tier requires uniform (arm, tier) across runs")

    n = len(runs)
    successes = sum(1 for r in runs if headline_metric(run=r))
    rate = successes / n
    stderr = math.sqrt(rate * (1 - rate) / n) if n > 0 else 0.0

    compile_ms = sorted(r.compile_ms for r in runs)
    answer_ms = sorted(r.answer_ms for r in runs)
    p50_compile = compile_ms[len(compile_ms) // 2]
    p50_answer = answer_ms[len(answer_ms) // 2]
    mean_cost = statistics.fmean(r.cost_usd for r in runs)

    return ArmAggregate(
        arm=arm,
        tier=tier,
        n=n,
        correctness_rate=rate,
        correctness_stderr=stderr,
        p50_compile_ms=p50_compile,
        p50_answer_ms=p50_answer,
        mean_cost_usd=mean_cost,
    )


def build_scaling_curves(
    *, runs: Iterable[QuestionRun]
) -> tuple[ScalingCurve, ...]:
    """Group runs by arm, then by tier (size ascending) — one curve per arm."""
    by_arm: dict[Arm, dict[HaystackTier, list[QuestionRun]]] = {}
    for run in runs:
        by_arm.setdefault(run.arm, {}).setdefault(run.tier, []).append(run)

    curves: list[ScalingCurve] = []
    for arm in sorted(by_arm, key=lambda a: a.value):
        tiers = sorted(by_arm[arm], key=lambda t: t.size_bytes)
        points = tuple(
            aggregate_arm_tier(runs=tuple(by_arm[arm][tier])) for tier in tiers
        )
        curves.append(ScalingCurve(arm=arm, points=points))
    return tuple(curves)
