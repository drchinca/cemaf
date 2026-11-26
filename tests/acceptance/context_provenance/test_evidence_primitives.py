"""Acceptance checks on the public context, citation, and recording contracts."""

from datetime import UTC, datetime

import pytest

from cemaf.citation.models import Citation
from cemaf.citation.tracker import CitationTracker
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import CompiledContext, PriorityContextCompiler, SimpleTokenEstimator
from cemaf.context.patch import SecurityLevel
from cemaf.context.source import ContextSource
from cemaf.core.enums import ExclusionReason, VerificationStatus
from cemaf.llm.factories import create_instrumented_client
from cemaf.llm.mock import MockLLMClient
from cemaf.llm.protocols import Message
from cemaf.observability.run_logger import InMemoryRunLogger, RunRecord


def _compiler() -> PriorityContextCompiler:
    return PriorityContextCompiler(token_estimator=SimpleTokenEstimator(chars_per_token=4))


@pytest.mark.context_acceptance("compiled_revision_ids")
async def test_selected_revision_ids_survive_compilation(policy_corpus):
    revisions = policy_corpus["policies"][:2]
    compiled = await _compiler().compile(
        clearance=SecurityLevel.CONFIDENTIAL,
        artifacts=tuple((item["source_id"], item["content"]) for item in revisions),
        memories=(),
        budget=TokenBudget(max_tokens=1000, reserved_for_output=0),
    )
    assert {source.source_id for source in compiled.sources} == {item["source_id"] for item in revisions}
    rendered = str(compiled.to_messages())
    for revision in revisions:
        assert revision["source_id"] in rendered
        assert revision["content"] in rendered


@pytest.mark.context_acceptance("selection_budget")
async def test_budget_selection_reports_omitted_evidence():
    compiled = await _compiler().compile(
        clearance=SecurityLevel.CONFIDENTIAL,
        artifacts=(("current", "a" * 80), ("older", "b" * 80)),
        memories=(),
        priorities={"current": 10, "older": 1},
        budget=TokenBudget(max_tokens=25, reserved_for_output=0),
    )
    assert compiled.within_budget()
    assert compiled.total_tokens == 20
    assert [source.source_id for source in compiled.sources] == ["current"]
    assert compiled.metadata["excluded_keys"] == ["older"]
    assert compiled.metadata["excluded_details"][0]["reason"] == ExclusionReason.BUDGET_EXCEEDED.value


@pytest.mark.context_acceptance("clearance_filter")
async def test_restricted_policy_never_enters_compiled_context(policy_corpus):
    permitted = policy_corpus["policies"][1]
    restricted = policy_corpus["policies"][4]
    compiled = await _compiler().compile(
        artifacts=tuple((p["source_id"], p["content"]) for p in (restricted, permitted)),
        memories=(),
        priorities={restricted["source_id"]: 100, permitted["source_id"]: 1},
        source_levels={restricted["source_id"]: SecurityLevel.CONFIDENTIAL},
        clearance=SecurityLevel.INTERNAL,
        budget=TokenBudget(max_tokens=25, reserved_for_output=0),
    )
    assert [source.source_id for source in compiled.sources] == [permitted["source_id"]]
    assert restricted["source_id"] in compiled.metadata["security_excluded"]
    assert "ALPHA-SECRET" not in str(compiled.to_messages())


@pytest.mark.context_acceptance("compaction_lineage")
async def test_summary_keeps_parent_identifiers():
    sources = tuple(
        ContextSource(content="policy evidence " * 30, source_type="artifact", source_id=key, token_count=120)
        for key in ("refunds@v1", "shipping@v1", "refunds@v2")
    )
    original = CompiledContext(
        sources=sources, total_tokens=360, budget=TokenBudget(max_tokens=1000, reserved_for_output=0)
    )

    async def summarize(text):
        return "Historical policies covered refunds and shipping."

    compacted = await _compiler().compact(compiled=original, preserve_recent=1, summarizer=summarize)
    summary, recent = compacted.sources
    assert set(summary.metadata["compacted_from"]) == {"refunds@v1", "shipping@v1"}
    assert recent.source_id == "refunds@v2"
    assert recent.content == sources[-1].content
    assert compacted.total_tokens < original.total_tokens
    assert summary.content in str(compacted.to_messages())
    assert summary.source_id in str(compacted.to_messages())


@pytest.mark.context_acceptance("citation_verification_status")
def test_citation_membership_does_not_assert_claim_truth():
    citation = Citation(
        id="claim-source",
        source_id="refunds@v2",
        source_type="document",
        quote="Returns are accepted within 30 days.",
    )
    tracker = CitationTracker()
    fact = tracker.create_cited_fact(fact="Returns are accepted within 90 days.", citations=(citation,))
    assert fact.is_cited
    assert fact.verification_status is VerificationStatus.UNVERIFIED


@pytest.mark.context_acceptance("recorded_messages")
async def test_exact_model_messages_and_citation_metadata_survive_round_trip(policy_corpus):
    policy = policy_corpus["policies"][1]
    compiled = await _compiler().compile(
        clearance=SecurityLevel.CONFIDENTIAL,
        artifacts=((policy["source_id"], policy["content"]),),
        memories=(),
        budget=TokenBudget(max_tokens=1000, reserved_for_output=0),
    )
    messages = [
        Message.system(compiled.to_messages()[0]["content"]),
        Message.user("What is the return window?"),
    ]
    logger = InMemoryRunLogger()
    client = create_instrumented_client(client=MockLLMClient(responses=["30 days"]), run_logger=logger)
    logger.start_run(run_id="policy-record")
    result = await client.complete(messages)
    record = RunRecord.from_dict(logger.end_run().to_dict())
    (call,) = record.llm_calls
    assert call.input_messages == [{"role": m.role.value, "content": m.content} for m in messages]
    assert call.output == result.content
    assert call.input_tokens == result.prompt_tokens
    citation = Citation(
        id="refunds",
        source_id=policy["source_id"],
        source_type="document",
        quote=policy["content"],
        retrieved_at=datetime(2026, 10, 20, tzinfo=UTC),
        metadata={"revision": policy["revision"], "effective_from": policy["effective_from"]},
    )
    assert Citation.from_dict(citation.to_dict()) == citation


@pytest.mark.context_acceptance("ordered_input_hash")
def test_different_rendered_order_has_a_different_fingerprint():
    sources = tuple(
        ContextSource(content=text, source_type="artifact", source_id=key)
        for key, text in (("a", "Instruction A"), ("b", "Instruction B"))
    )
    first = CompiledContext(sources=sources, total_tokens=8, budget=TokenBudget(max_tokens=100))
    second = CompiledContext(sources=tuple(reversed(sources)), total_tokens=8, budget=first.budget)
    assert first.to_messages() != second.to_messages()
    assert first.content_hash != second.content_hash
