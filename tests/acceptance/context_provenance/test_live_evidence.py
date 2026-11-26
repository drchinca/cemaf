"""Explicit live-provider and human-pilot evidence; never replace missing runs with mocks."""

import json
import os
from datetime import date
from pathlib import Path

import pytest

from cemaf.evals.pilot import PilotStudy, evaluate_pilot, verify_pilot_artifacts
from cemaf.llm.factories import create_llm_client
from cemaf.llm.preflight import RequestTokenCounter
from cemaf.persistence.evidence import SQLiteEvidenceStore


@pytest.mark.context_acceptance("model_portability")
@pytest.mark.parametrize(
    "provider,credential,default_model",
    [
        ("openai", "OPENAI_API_KEY", "gpt-5.5"),
        ("gemini", "GEMINI_API_KEY", "gemini-3.5-flash-lite"),
    ],
)
async def test_real_providers_preserve_versioned_evidence(
    tmp_path,
    policy_corpus,
    policy_app,
    provider,
    credential,
    default_model,
    record_property,
):
    if os.getenv("CEMAF_RUN_CONTEXT_PROVENANCE_LIVE") != "1" or not os.getenv(credential):
        pytest.skip(f"Live evidence requires CEMAF_RUN_CONTEXT_PROVENANCE_LIVE=1 and {credential}")
    model = os.getenv(f"CEMAF_PILOT_{provider.upper()}_MODEL", default_model)
    client = create_llm_client(provider, model=model, temperature=0, max_tokens=1000, timeout_seconds=15)
    assert isinstance(client, RequestTokenCounter)
    policies = [p for p in policy_corpus["policies"] if not p["source_id"].endswith("@conflict")]
    evidence_root = Path(os.getenv("CEMAF_PILOT_EVIDENCE_DIR", str(tmp_path))) / provider
    for day, revision in ((date(2026, 5, 1), "v1"), (date(2026, 10, 20), "v2"), (date(2027, 2, 1), "future")):
        answer = await policy_app.answer_policy(
            root=evidence_root,
            policies=policies,
            as_of=day,
            client=client,
            counter=client,
            run_id=f"portability-{provider}-{revision}",
        )
        assert answer.status == "published", f"Live {provider} run did not pass evidence/publication gates"
        store = SQLiteEvidenceStore(path=evidence_root / "evidence.sqlite", tenant_id="a")
        record = store.load(answer.evidence_id)
        assert record.request.schema_version == "cemaf.request-evidence.v1"
        assert record.request.context.artifact_refs[0].version == revision
        assert record.request.context.artifact_refs[0].artifact_id == "refunds"
        response = json.loads(record.response_json)
        assert response["model"] and response["prompt_tokens"] > 0 and response["completion_tokens"] > 0
        record_property(f"{provider}_{revision}_evidence_id", record.evidence_id)
        record_property(f"{provider}_{revision}_model", response["model"])


@pytest.mark.context_acceptance("pilot_value")
def test_independent_workload_and_human_review_meet_pilot_targets():
    path = os.getenv("CEMAF_POLICY_PILOT_STUDY")
    if not path:
        pytest.skip("Requires CEMAF_POLICY_PILOT_STUDY with real matched runs and independent human review")
    study = PilotStudy.model_validate_json(Path(path).read_text())
    verify_pilot_artifacts(study, root=Path(path).parent / "artifacts")
    report = evaluate_pilot(study)
    assert report["graduated"], report["reasons"]
