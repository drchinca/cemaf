"""Synthetic tests validate the study machinery, not a business-value claim."""

from collections import Counter

import pytest

from cemaf.context.manifest import ContentDigest, canonical_json
from cemaf.evals.pilot import (
    PilotObservation,
    PilotStudy,
    create_review_assignments,
    evaluate_pilot,
    implementation_digest,
    verify_pilot_artifacts,
)


def _conditions(question_ids=()):
    return canonical_json(
        {
            "model_version": "test-provider-version",
            "corpus_digest": "corpus",
            "retrieval_digest": "retrieval",
            "output_budget": 1000,
            "prompt_version": "1",
            "question_order_digest": ContentDigest.of(canonical_json(question_ids).encode()).digest,
        }
    )


def test_reviews_are_blinded_counterbalanced_and_never_repeat_a_question_for_a_reviewer():
    assignments = create_review_assignments(
        question_ids=tuple(f"q{i}" for i in range(102)), reviewer_ids=("r1", "r2", "r3"), seed=17
    )
    assert len(assignments) == 306 and len({assignment.blind_id for assignment in assignments}) == 306
    assert len({(assignment.reviewer_id, assignment.question_id) for assignment in assignments}) == 306
    counts = Counter((assignment.reviewer_id, assignment.arm) for assignment in assignments)
    assert set(counts.values()) == {34}
    assert assignments == create_review_assignments(
        question_ids=tuple(f"q{i}" for i in range(102)), reviewer_ids=("r1", "r2", "r3"), seed=17
    )
    with pytest.raises(ValueError):
        create_review_assignments(question_ids=("q",), reviewer_ids=("r1", "r2"), seed=17)


def test_no_human_or_live_evidence_cannot_graduate():
    study = PilotStudy(
        implementation_digest=implementation_digest(),
        dataset_digest=ContentDigest.of(b"test-fixture"),
        conditions_json=_conditions(),
        max_cost_ratio=2,
        max_latency_ratio=2,
        observations=(),
    )
    result = evaluate_pilot(study)
    assert not result["graduated"] and result["questions"] == 0
    assert "100 unique" in str(result["reasons"])


def test_implementation_change_invalidates_old_study():
    study = PilotStudy(
        implementation_digest="old-code",
        dataset_digest=ContentDigest.of(b"test-fixture"),
        conditions_json=_conditions(),
        max_cost_ratio=2,
        max_latency_ratio=2,
        observations=(),
    )
    assert "Implementation changed" in str(evaluate_pilot(study)["reasons"])


def _synthetic_study():
    questions = tuple(f"q{i}" for i in range(100))
    conditions = _conditions(questions)
    assignments = create_review_assignments(question_ids=questions, reviewer_ids=("r1", "r2", "r3"), seed=17)
    reviewers = {(a.question_id, a.arm): a.reviewer_id for a in assignments}
    rows = tuple(
        PilotObservation(
            question_id=q,
            question_index=i,
            arm=arm,
            conditions_digest=ContentDigest.of(conditions.encode()),
            run_record_digest=ContentDigest.of(f"{q}:{arm}".encode()),
            provider_model_version="test-provider-version",
            live_provider=True,
            input_tokens=100,
            output_tokens=20,
            cost_usd=0.001,
            cost_profile_id="test-prices",
            latency_ms=20,
            review_seconds=60 if arm == "cemaf" else 100,
            reviewer_id=reviewers[q, arm],
            review_receipt_digest=ContentDigest.of(f"review:{q}:{arm}".encode()),
            human_review=True,
            blinded=True,
            independent_labeler_id="labeler",
            label_digest=ContentDigest.of(q.encode()),
            claim_count=1,
            unsupported_claim_count=0,
            unauthorized_evidence_count=0,
            impact_true_positives=1,
            impact_false_positives=0,
            impact_false_negatives=0,
        )
        for i, q in enumerate(questions)
        for arm in ("simple", "citation", "cemaf")
    )
    return PilotStudy(
        implementation_digest=implementation_digest(),
        dataset_digest=ContentDigest.of(b"fixture"),
        conditions_json=conditions,
        max_cost_ratio=2,
        max_latency_ratio=2,
        observations=rows,
    )


def test_paired_pilot_statistics_and_failure_conditions_use_complete_rows():
    # Synthetic observations test the calculation, not the truth of human attestations.
    study = _synthetic_study()
    report = evaluate_pilot(study)
    assert report["graduated"]
    assert report["verification_time_reduction"] == pytest.approx(0.4)
    assert report["paired_bootstrap_95_percent"] == pytest.approx([0.4, 0.4])
    first = study.observations[0]
    for change in (
        {"live_provider": False},
        {"human_review": False},
        {"blinded": False},
        {"conditions_digest": ContentDigest.of(b"wrong")},
        {"provider_model_version": "wrong"},
    ):
        invalid = study.model_copy(
            update={"observations": (first.model_copy(update=change), *study.observations[1:])}
        )
        assert not evaluate_pilot(invalid)["graduated"]
    duplicated = study.model_copy(update={"observations": (*study.observations, first)})
    assert not evaluate_pilot(duplicated)["graduated"]
    excessive_cost = study.model_copy(update={"max_cost_ratio": 0.5})
    assert not evaluate_pilot(excessive_cost)["graduated"]
    disclosure = tuple(
        row.model_copy(update={"unauthorized_evidence_count": 1}) if row.arm == "cemaf" else row
        for row in study.observations
    )
    assert not evaluate_pilot(study.model_copy(update={"observations": disclosure}))["graduated"]


def test_missing_artifact_receipts_cannot_satisfy_adoption(tmp_path):
    with pytest.raises(FileNotFoundError):
        verify_pilot_artifacts(_synthetic_study(), root=tmp_path)
