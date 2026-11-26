"""Blinded review assignments and a fail-closed matched-pilot evidence gate.

Human/label provenance is supplied by the study operator. This module checks
completeness and comparisons; it cannot authenticate a person's attestation.
"""

from __future__ import annotations

import hashlib
import json
import random
import statistics
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from cemaf.context.manifest import ContentDigest, ImmutableModel, canonical_json

PilotArm = Literal["simple", "citation", "cemaf"]
_ARMS: tuple[PilotArm, ...] = ("simple", "citation", "cemaf")


def implementation_digest() -> str:
    """Invalidate evidence when any installed framework source changes."""
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


class ReviewAssignment(ImmutableModel):
    blind_id: str
    question_id: str
    arm: PilotArm
    reviewer_id: str
    order: int


def create_review_assignments(
    *,
    question_ids: tuple[str, ...],
    reviewer_ids: tuple[str, ...],
    seed: int,
) -> tuple[ReviewAssignment, ...]:
    """Counterbalance arms without showing any reviewer the same question twice.

    Keep the returned arm mapping private; reviewers receive blind_id, question,
    answer, and evidence only. Export each reviewer's rows in the declared order.
    """
    if len(reviewer_ids) < 3 or len(set(reviewer_ids)) != len(reviewer_ids):
        raise ValueError("Blinded comparison requires at least three distinct reviewers")
    if not question_ids or len(set(question_ids)) != len(question_ids):
        raise ValueError("Question identities must be nonempty and unique")
    rng = random.Random(seed)  # nosec B311 -- repeatable study assignment, not a security token
    assignments: list[ReviewAssignment] = []
    question_order = list(question_ids)
    rng.shuffle(question_order)
    arms = list(_ARMS)
    rng.shuffle(arms)
    for index, question_id in enumerate(question_order):
        for arm_index, arm in enumerate(arms):
            reviewer = reviewer_ids[(index + arm_index) % len(reviewer_ids)]
            blind_id = ContentDigest.of(canonical_json([seed, question_id, arm, reviewer]).encode()).digest
            assignments.append(
                ReviewAssignment(
                    blind_id=blind_id, question_id=question_id, arm=arm, reviewer_id=reviewer, order=index
                )
            )
    return tuple(assignments)


class PilotObservation(ImmutableModel):
    question_id: str
    question_index: int = Field(ge=0)
    arm: PilotArm
    conditions_digest: ContentDigest
    run_record_digest: ContentDigest
    provider_model_version: str = Field(min_length=1)
    live_provider: bool
    input_tokens: int = Field(gt=0)
    output_tokens: int = Field(gt=0)
    cost_usd: float = Field(ge=0, allow_inf_nan=False)
    cost_profile_id: str = Field(min_length=1)
    latency_ms: float = Field(gt=0, allow_inf_nan=False)
    review_seconds: float = Field(gt=0, allow_inf_nan=False)
    reviewer_id: str = Field(min_length=1)
    review_receipt_digest: ContentDigest
    human_review: bool
    blinded: bool
    independent_labeler_id: str = Field(min_length=1)
    label_digest: ContentDigest
    claim_count: int = Field(ge=0)
    unsupported_claim_count: int = Field(ge=0)
    unauthorized_evidence_count: int = Field(ge=0)
    impact_true_positives: int = Field(ge=0)
    impact_false_positives: int = Field(ge=0)
    impact_false_negatives: int = Field(ge=0)


class PilotStudy(ImmutableModel):
    schema_version: Literal["cemaf.policy-pilot.v1"] = "cemaf.policy-pilot.v1"
    implementation_digest: str
    dataset_digest: ContentDigest
    # These common conditions pin model/corpus/retrieval/settings/question order.
    conditions_json: str
    max_cost_ratio: float = Field(gt=0, allow_inf_nan=False)
    max_latency_ratio: float = Field(gt=0, allow_inf_nan=False)
    observations: tuple[PilotObservation, ...]

    @model_validator(mode="after")
    def validate_conditions(self) -> PilotStudy:
        conditions = json.loads(self.conditions_json)
        required = {
            "model_version",
            "corpus_digest",
            "retrieval_digest",
            "output_budget",
            "question_order_digest",
            "prompt_version",
        }
        if (
            not isinstance(conditions, dict)
            or not required <= conditions.keys()
            or not all(conditions[key] for key in required)
            or canonical_json(conditions) != self.conditions_json
        ):
            raise ValueError(
                "Pilot conditions must pin model, corpus, retrieval, budget, question order, and prompt"
            )
        return self


def verify_pilot_artifacts(study: PilotStudy, *, root: Path) -> None:
    """Resolve content-addressed run/label/review receipts before adoption.

    Study operators remain responsible for the authenticity of human attestations
    and provider traces. Missing or modified artifact bytes cannot satisfy a gate.
    """
    categories: set[str] = set()
    for row in study.observations:
        artifacts = []
        for digest in (row.run_record_digest, row.label_digest, row.review_receipt_digest):
            content = (root / f"{digest.digest}.json").read_bytes()
            if ContentDigest.of(content) != digest:
                raise ValueError("Pilot artifact failed integrity verification")
            artifacts.append(json.loads(content))
        run, label, review = artifacts
        calls = run.get("llm_calls", [])
        if (
            not calls
            or any(call.get("model") != row.provider_model_version for call in calls)
            or sum(call.get("input_tokens", 0) for call in calls) != row.input_tokens
            or sum(call.get("output_tokens", 0) for call in calls) != row.output_tokens
        ):
            raise ValueError("Pilot observation does not match the recorded provider usage")
        if (
            label.get("question_id") != row.question_id
            or label.get("labeler_id") != row.independent_labeler_id
            or label.get("human") is not True
        ):
            raise ValueError("Missing independent human label receipt")
        if (
            review.get("question_id") != row.question_id
            or review.get("reviewer_id") != row.reviewer_id
            or review.get("human") is not True
            or review.get("review_seconds") != row.review_seconds
        ):
            raise ValueError("Missing matching human review receipt")
        categories.add(str(label.get("category", "")))
    if (
        not {"ordinary", "stale", "conflict", "unauthorized", "injection", "revocation", "source_change"}
        <= categories
    ):
        raise ValueError("Pilot labels must cover ordinary and adversarial policy categories")


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * quantile))]


def evaluate_pilot(study: PilotStudy) -> dict[str, object]:
    """Require real, matched observations and human review before a value verdict."""
    reasons: list[str] = []
    if study.implementation_digest != implementation_digest():
        reasons.append("Implementation changed; evidence must be regenerated")
    expected_conditions = ContentDigest.of(study.conditions_json.encode())
    conditions = json.loads(study.conditions_json)
    rows: dict[str, dict[PilotArm, PilotObservation]] = {}
    for observation in study.observations:
        by_arm = rows.setdefault(observation.question_id, {})
        if observation.arm in by_arm:
            reasons.append("Duplicate question/arm observation")
        by_arm[observation.arm] = observation
        if (
            not observation.live_provider
            or not observation.human_review
            or not observation.blinded
            or observation.conditions_digest != expected_conditions
            or observation.provider_model_version != conditions["model_version"]
        ):
            reasons.append("Missing live, blinded, human, or matched-condition evidence")
        if observation.unsupported_claim_count > observation.claim_count:
            reasons.append("Invalid claim labels")
    if len(rows) < 100 or any(set(by_arm) != set(_ARMS) for by_arm in rows.values()):
        reasons.append(
            "At least 100 unique independently labeled questions across all three arms are required"
        )
    if reasons:
        return {"graduated": False, "reasons": sorted(set(reasons)), "questions": len(rows)}
    ordered_questions = sorted(rows, key=lambda question_id: rows[question_id]["cemaf"].question_index)
    if (
        len({rows[question_id]["cemaf"].question_index for question_id in rows}) != len(rows)
        or ContentDigest.of(canonical_json(ordered_questions).encode()).digest
        != conditions["question_order_digest"]
    ):
        reasons.append("Question order does not match the predeclared workload")
    for by_arm in rows.values():
        observations = list(by_arm.values())
        if len({row.reviewer_id for row in observations}) != 3:
            reasons.append("A reviewer saw multiple answers to the same question")
        if (
            len(
                {
                    (row.question_index, row.provider_model_version, row.label_digest.digest)
                    for row in observations
                }
            )
            != 1
        ):
            reasons.append("Unmatched model, question order, or independent labels")
        if any(row.independent_labeler_id == row.reviewer_id for row in observations):
            reasons.append("Labeling and blinded review must be independent")
    baseline = [by_arm["citation"] for by_arm in rows.values()]
    cemaf = [by_arm["cemaf"] for by_arm in rows.values()]
    baseline_time = statistics.median(row.review_seconds for row in baseline)
    cemaf_time = statistics.median(row.review_seconds for row in cemaf)
    reduction = 1 - cemaf_time / baseline_time
    rng = random.Random(17)  # nosec B311 -- paired bootstrap
    pairs = [
        (base.review_seconds, candidate.review_seconds)
        for base, candidate in zip(baseline, cemaf, strict=True)
    ]
    samples = []
    for _ in range(1000):
        sample = rng.choices(pairs, k=len(pairs))
        samples.append(
            1 - statistics.median(pair[1] for pair in sample) / statistics.median(pair[0] for pair in sample)
        )
    cost_base = sum(row.cost_usd for row in baseline)
    cost_ratio = sum(row.cost_usd for row in cemaf) / cost_base if cost_base > 0 else None
    latency_ratio = _percentile([row.latency_ms for row in cemaf], 0.95) / _percentile(
        [row.latency_ms for row in baseline], 0.95
    )
    if reduction < 0.30:
        reasons.append("Median verification-time reduction is below the predeclared 30% target")
    if any(row.unauthorized_evidence_count for row in cemaf):
        reasons.append("Unauthorized evidence was disclosed")
    if any(row.impact_false_positives or row.impact_false_negatives for row in cemaf):
        reasons.append("Source-change impact labels did not match")
    if sum(row.impact_true_positives for row in cemaf) == 0:
        reasons.append("No positive source-change impact evidence")
    if not any(row.claim_count for row in cemaf):
        reasons.append("No accepted claim-support evidence")
    if cost_ratio is None or cost_ratio > study.max_cost_ratio or latency_ratio > study.max_latency_ratio:
        reasons.append("Cost or latency evidence is missing or exceeds its predeclared ceiling")
    metrics = {}
    for arm in _ARMS:
        arm_rows = [by_arm[arm] for by_arm in rows.values()]
        claims = sum(row.claim_count for row in arm_rows)
        metrics[arm] = {
            "unsupported_claim_rate": sum(row.unsupported_claim_count for row in arm_rows) / claims
            if claims
            else None,
            "unauthorized_evidence": sum(row.unauthorized_evidence_count for row in arm_rows),
            "review_seconds_median": statistics.median(row.review_seconds for row in arm_rows),
            "latency_p50_ms": _percentile([row.latency_ms for row in arm_rows], 0.5),
            "latency_p95_ms": _percentile([row.latency_ms for row in arm_rows], 0.95),
            "total_cost_usd": sum(row.cost_usd for row in arm_rows),
        }
    return {
        "graduated": not reasons,
        "reasons": sorted(set(reasons)),
        "questions": len(rows),
        "verification_time_reduction": reduction,
        "paired_bootstrap_95_percent": [_percentile(samples, 0.025), _percentile(samples, 0.975)],
        "cost_ratio": cost_ratio,
        "latency_p95_ratio": latency_ratio,
        "arms": metrics,
    }
