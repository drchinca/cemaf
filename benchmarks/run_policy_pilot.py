"""Run bounded matched policy comparisons and prepare private blinded review packets.

The default is an OFFLINE demonstration with three fixture questions. It never
produces a graduated value report. --live requires credentials; --dataset accepts
an operator's independently labeled workload. --study evaluates collected human
review observations using the framework's pilot gate.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

from cemaf.context.manifest import ContentDigest, canonical_json
from cemaf.evals.pilot import (
    PilotStudy,
    create_review_assignments,
    evaluate_pilot,
    implementation_digest,
    verify_pilot_artifacts,
)
from cemaf.llm.factories import create_llm_client
from cemaf.llm.mock import MockLLMClient
from cemaf.llm.preflight import LLMRequestTokenCounter, RequestTokenCounter
from cemaf.llm.protocols import LLMConfig, Message
from cemaf.observability.run_logger import RunRecord
from cemaf.persistence.atomic_file import atomic_write_text

ROOT = Path(__file__).resolve().parents[1]


def _application():
    spec = importlib.util.spec_from_file_location(
        "pilot_policy_app", ROOT / "examples/app_shapes/policy_evidence.py"
    )
    assert spec is not None and spec.loader is not None
    app = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = app
    spec.loader.exec_module(app)
    return app


def _save(path: Path, value: object) -> None:
    atomic_write_text(path, canonical_json(value), keep_backup=False)
    path.chmod(0o600)


async def run_comparison(
    *,
    output: Path,
    dataset: Path | None = None,
    corpus_path: Path | None = None,
    live: bool = False,
    limit: int = 3,
) -> dict[str, object]:
    if limit < 1 or limit > 1000:
        raise ValueError("Question limit must be between 1 and 1000")
    app = _application()
    corpus = json.loads(
        (corpus_path or ROOT / "tests/acceptance/context_provenance/policies.json").read_text()
    )
    policies = (
        corpus["policies"]
        if corpus_path
        else [p for p in corpus["policies"] if not p["source_id"].endswith("@conflict")]
    )
    questions = (
        json.loads(dataset.read_text())
        if dataset
        else [
            {"id": "historical", "question": "What is the approved return window?", "as_of": "2026-05-01"},
            {"id": "current", "question": "What is the approved return window?", "as_of": "2026-10-20"},
            {"id": "future", "question": "What is the approved return window?", "as_of": "2027-02-01"},
        ]
    )[:limit]
    if not questions or len({q["id"] for q in questions}) != len(questions):
        raise ValueError("Dataset must contain unique question IDs")
    output.mkdir(parents=True, exist_ok=True)
    output.chmod(0o700)
    providers = (
        (("openai", "OPENAI_API_KEY", "gpt-5.5"), ("gemini", "GEMINI_API_KEY", "gemini-3.5-flash-lite"))
        if live
        else (("offline", "", "offline-policy-fixture"),)
    )
    results, failures = [], []
    for provider, credential, default_model in providers:
        if live and not os.getenv(credential):
            failures.append({"provider": provider, "status": "not_run", "reason": f"Missing {credential}"})
            continue
        model = os.getenv(f"CEMAF_PILOT_{provider.upper()}_MODEL", default_model)
        client = (
            create_llm_client(provider, model=model, max_tokens=1000, temperature=0, timeout_seconds=15)
            if live
            else MockLLMClient(config=LLMConfig(model=model, max_tokens=1000, temperature=0))
        )
        counter = client if isinstance(client, RequestTokenCounter) else LLMRequestTokenCounter(client)
        try:
            await counter.count_request(messages=[Message.user("Preflight")], tools=[], config=client.config)
        except Exception as exc:
            failures.append(
                {
                    "provider": provider,
                    "status": "failed_preflight",
                    "error_type": type(exc).__name__,
                    "status_code": getattr(exc, "status_code", None),
                }
            )
            continue
        conditions = {
            "implementation_digest": implementation_digest(),
            "model": model,
            "corpus_digest": ContentDigest.of(canonical_json(policies).encode()).digest,
            "retrieval": "latest-approved-effective-policy-v1",
            "output_budget": 1000,
            "question_order": [q["id"] for q in questions],
            "shared_executor_harness": True,
            "live": live,
        }
        for index, question in enumerate(questions):
            day = date.fromisoformat(question["as_of"])
            policy, _ = app.select_policy_revision(
                policies=policies, tenant="a", policy_id="tenant-a/refunds", as_of=day
            )
            for arm in ("simple", "citation", "cemaf"):
                if not live and policy is not None:
                    text = (
                        app.example_claim(
                            source_id=canonical_json(["a", "refunds", policy["revision"]]),
                            text=policy["content"],
                        )
                        if arm == "cemaf"
                        else policy["content"]
                    )
                    client = MockLLMClient(responses=[text], config=LLMConfig(model=model, max_tokens=1000))
                    counter = LLMRequestTokenCounter(client)
                run_id = f"pilot-{provider}-{index}-{arm}"
                run_root = output / "private" / provider / arm / str(index)
                kwargs = {
                    "root": run_root,
                    "policies": policies,
                    "as_of": day,
                    "client": client,
                    "counter": counter,
                    "require_exact": live,
                    "question": question["question"],
                    "run_id": run_id,
                }
                answer = (
                    await app.answer_policy(**kwargs)
                    if arm == "cemaf"
                    else await app.answer_baseline(**kwargs, arm=arm)
                )
                path = run_root / "runs" / f"live__{run_id}" / "run_record.json"
                record = RunRecord.from_dict(json.loads(path.read_text())) if path.exists() else None
                results.append(
                    {
                        "provider": provider,
                        "arm": arm,
                        "question_id": question["id"],
                        "question_index": index,
                        "conditions": conditions,
                        **asdict(answer),
                        "latency_ms": record.duration_ms if record else None,
                        "tokens": record.total_tokens if record else None,
                        "run_record_digest": ContentDigest.of(path.read_bytes()).digest if record else None,
                        "run_record_path": str(path) if record else None,
                        "provider_model_version": record.llm_calls[0].model
                        if record and record.llm_calls
                        else None,
                        "cost_usd": None,
                        "cost_status": "requires documented model price profile or invoice",
                    }
                )
        assignments = create_review_assignments(
            question_ids=tuple(q["id"] for q in questions),
            reviewer_ids=("reviewer-1", "reviewer-2", "reviewer-3"),
            seed=17,
        )
        _save(output / "private" / provider / "assignments.json", [a.model_dump() for a in assignments])
        by_question = {
            (row["question_id"], row["arm"]): row for row in results if row["provider"] == provider
        }
        for reviewer in ("reviewer-1", "reviewer-2", "reviewer-3"):
            packet = []
            for assignment in assignments:
                if assignment.reviewer_id != reviewer:
                    continue
                row = by_question[(assignment.question_id, assignment.arm)]
                evidence_refs = []
                if row["run_record_path"] and Path(row["run_record_path"]).exists():
                    run = RunRecord.from_dict(json.loads(Path(row["run_record_path"]).read_text()))
                    if run.llm_calls:
                        evidence_refs = [
                            json.loads(message["content"])
                            for message in run.llm_calls[0].input_messages
                            if message.get("metadata", {}).get("trust") == "untrusted_evidence"
                        ]
                packet.append(
                    {
                        "blind_id": assignment.blind_id,
                        "question_id": assignment.question_id,
                        "question": next(
                            q["question"] for q in questions if q["id"] == assignment.question_id
                        ),
                        "answer": row["answer"],
                        "evidence": evidence_refs,
                        "review_seconds": None,
                        "support_verdict": None,
                        "independent_label_digest": None,
                    }
                )
            _save(output / "reviews" / provider / f"{reviewer}.json", packet)
    report = {
        "schema_version": "cemaf.policy-pilot-runs.v1",
        "mode": "live" if live else "offline_demo",
        "graduated": False,
        "questions": len(questions),
        "results": results,
        "provider_failures": failures,
        "missing_evidence": [
            "independent workload labels",
            "completed blinded human reviews",
            "predeclared cost and latency ceilings",
            "documented actual cost profile",
        ],
        "implementation_digest": implementation_digest(),
    }
    _save(output / "private" / "runs.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/tmp/cemaf-policy-pilot"))
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--study", type=Path)
    args = parser.parse_args()
    if args.study:
        study = PilotStudy.model_validate_json(args.study.read_text())
        verify_pilot_artifacts(study, root=args.study.parent / "artifacts")
        report = evaluate_pilot(study)
        _save(args.output / "value-report.json", report)
        print(canonical_json(report))
        return 0 if report["graduated"] else 1
    report = asyncio.run(
        run_comparison(
            output=args.output,
            dataset=args.dataset,
            corpus_path=args.corpus,
            live=args.live,
            limit=args.limit,
        )
    )
    print(canonical_json({key: value for key, value in report.items() if key != "results"}))
    return 1 if report["provider_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
