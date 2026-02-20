"""Tests for Glass Box Report Generator."""

import pytest

from cemaf.core.enums import ExclusionReason
from cemaf.core.provenance import ProvenanceChain, ProvenanceLink, SourceReference
from cemaf.core.types import AgentID, NodeID, ProvenanceID, RunID
from cemaf.observability.glass_box import (
    CitationCoverage,
    CostBreakdown,
    GlassBoxReporter,
    TokenAudit,
)
from cemaf.observability.run_logger import LLMCall, RunRecord


def _make_source(
    source_id: str,
    *,
    token_count: int = 500,
    included: bool = True,
    exclusion_reason: ExclusionReason | None = None,
) -> SourceReference:
    """Create a SourceReference for testing."""
    return SourceReference(
        source_id=source_id,
        source_type="document",
        token_count=token_count,
        priority=1,
        included=included,
        exclusion_reason=exclusion_reason,
    )


def _make_link(
    llm_call_id: str,
    *,
    node_id: str | None = None,
    agent_id: str | None = None,
    sources: tuple[SourceReference, ...] = (),
    citation_ids: tuple[str, ...] = (),
    cost_usd: float = 0.1,
) -> ProvenanceLink:
    """Create a ProvenanceLink for testing."""
    return ProvenanceLink(
        id=ProvenanceID(f"prov_{llm_call_id}"),
        llm_call_id=llm_call_id,
        node_id=NodeID(node_id) if node_id else None,
        agent_id=AgentID(agent_id) if agent_id else None,
        context_sources=sources,
        citation_ids=citation_ids,
        cost_usd=cost_usd,
    )


def _make_llm_call(
    call_id: str,
    *,
    model: str = "claude-sonnet-4-6",
    node_id: str | None = None,
    agent_id: str | None = None,
    input_tokens: int = 1000,
    output_tokens: int = 200,
    cost_usd: float = 0.01,
    output: str = "LLM output",
    context_sources_used: tuple[str, ...] = (),
) -> LLMCall:
    """Create an LLMCall for testing."""
    return LLMCall(
        id=call_id,
        model=model,
        input_messages=[{"role": "user", "content": "test"}],
        output=output,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        node_id=node_id,
        agent_id=agent_id,
        cost_usd=cost_usd,
        context_sources_used=context_sources_used,
    )


def _make_record(
    *,
    run_id: str = "run_001",
    llm_calls: list[LLMCall] | None = None,
    chain: ProvenanceChain | None = None,
    total_cost_usd: float = 0.0,
    success: bool = True,
) -> RunRecord:
    """Create a RunRecord for testing."""
    record = RunRecord(run_id=run_id, success=success, total_cost_usd=total_cost_usd)
    record.llm_calls = llm_calls or []
    record.provenance_chain = chain
    return record


class TestGlassBoxReporter:
    """Tests for GlassBoxReporter."""

    def test_generate_empty_record(self) -> None:
        """Report generates cleanly from an empty record."""
        reporter = GlassBoxReporter()
        record = _make_record()
        report = reporter.generate(record=record)

        assert report.run_id == "run_001"
        assert report.success is True
        assert report.provenance_chain is None
        assert report.citation_coverage.coverage_ratio == 1.0
        assert report.token_audit.total_input_tokens == 0
        assert report.cost_breakdown.total_cost_usd == 0.0
        assert len(report.decision_trace) == 0

    def test_generate_with_llm_calls_no_provenance(self) -> None:
        """Report builds decision trace from LLM calls when no provenance chain."""
        calls = [
            _make_llm_call("llm_1", node_id="step_0", agent_id="librarian"),
            _make_llm_call("llm_2", node_id="step_1", agent_id="summarizer"),
        ]
        record = _make_record(llm_calls=calls)
        reporter = GlassBoxReporter()
        report = reporter.generate(record=record)

        assert len(report.decision_trace) == 2
        assert report.decision_trace[0].llm_call_id == "llm_1"
        assert report.decision_trace[0].node_id == "step_0"
        assert report.decision_trace[1].agent_id == "summarizer"

    def test_generate_with_full_provenance(self) -> None:
        """Report cross-references provenance chain with LLM calls."""
        src_a = _make_source("src_a", token_count=500)
        src_b = _make_source(
            "src_b",
            token_count=300,
            included=False,
            exclusion_reason=ExclusionReason.BUDGET_EXCEEDED,
        )

        link = _make_link(
            "llm_1",
            node_id="step_0",
            agent_id="librarian",
            sources=(src_a, src_b),
            citation_ids=("cite_1", "cite_2"),
            cost_usd=0.05,
        )
        chain = ProvenanceChain(run_id=RunID("run_001"), links=(link,))

        calls = [_make_llm_call("llm_1", node_id="step_0", agent_id="librarian", cost_usd=0.05)]
        record = _make_record(llm_calls=calls, chain=chain, total_cost_usd=0.05)

        reporter = GlassBoxReporter()
        report = reporter.generate(record=record)

        # Decision trace
        assert len(report.decision_trace) == 1
        step = report.decision_trace[0]
        assert step.sources_seen == ("src_a",)
        assert step.sources_excluded == ("src_b",)
        assert step.citation_ids == ("cite_1", "cite_2")

        # Token audit
        assert report.token_audit.sources_included == 1
        assert report.token_audit.sources_excluded == 1
        assert report.token_audit.exclusion_reasons["budget_exceeded"] == 1
        assert report.token_audit.by_source["src_a"] == 500
        assert report.token_audit.by_source["src_b"] == 300

        # Citation coverage
        assert report.citation_coverage.total_citations == 2
        assert report.citation_coverage.verified_citations == 2
        assert report.citation_coverage.coverage_ratio == 1.0

    def test_decision_trace_output_preview_truncated(self) -> None:
        """Output preview is truncated to 200 characters."""
        long_output = "x" * 500
        calls = [_make_llm_call("llm_1", output=long_output)]
        link = _make_link("llm_1", cost_usd=0.01)
        chain = ProvenanceChain(run_id=RunID("run_001"), links=(link,))
        record = _make_record(llm_calls=calls, chain=chain)

        reporter = GlassBoxReporter()
        report = reporter.generate(record=record)
        assert len(report.decision_trace[0].output_preview) == 200

    def test_token_audit_by_node_and_agent(self) -> None:
        """Token audit breaks down tokens by node and agent."""
        calls = [
            _make_llm_call(
                "llm_1",
                node_id="step_0",
                agent_id="librarian",
                input_tokens=1000,
                output_tokens=200,
            ),
            _make_llm_call(
                "llm_2",
                node_id="step_0",
                agent_id="librarian",
                input_tokens=500,
                output_tokens=100,
            ),
            _make_llm_call(
                "llm_3",
                node_id="step_1",
                agent_id="summarizer",
                input_tokens=800,
                output_tokens=150,
            ),
        ]
        record = _make_record(llm_calls=calls)
        reporter = GlassBoxReporter()
        audit = reporter.generate_token_audit(record=record)

        assert audit.total_input_tokens == 2300
        assert audit.total_output_tokens == 450
        assert audit.by_node["step_0"]["input_tokens"] == 1500
        assert audit.by_node["step_1"]["output_tokens"] == 150
        assert audit.by_agent["librarian"]["input_tokens"] == 1500
        assert audit.by_agent["summarizer"]["input_tokens"] == 800

    def test_cost_breakdown_by_model(self) -> None:
        """Cost breakdown aggregates per model."""
        calls = [
            _make_llm_call("llm_1", model="claude-sonnet-4-6", cost_usd=0.01),
            _make_llm_call("llm_2", model="claude-sonnet-4-6", cost_usd=0.02),
            _make_llm_call("llm_3", model="claude-opus-4-6", cost_usd=0.10),
        ]
        record = _make_record(llm_calls=calls, total_cost_usd=0.13)
        reporter = GlassBoxReporter()
        report = reporter.generate(record=record)

        assert report.cost_breakdown.by_model["claude-sonnet-4-6"] == pytest.approx(0.03)
        assert report.cost_breakdown.by_model["claude-opus-4-6"] == pytest.approx(0.10)
        assert report.cost_breakdown.total_cost_usd == pytest.approx(0.13)

    def test_citation_coverage_unverified(self) -> None:
        """Citations without included sources are flagged as unverified."""
        # Link with no included sources but a citation
        link = _make_link(
            "llm_1",
            sources=(_make_source("src_a", included=False, exclusion_reason=ExclusionReason.LOW_PRIORITY),),
            citation_ids=("cite_orphan",),
        )
        chain = ProvenanceChain(run_id=RunID("run_001"), links=(link,))
        record = _make_record(chain=chain)

        reporter = GlassBoxReporter()
        coverage = reporter.verify_citation_coverage(record=record)

        assert coverage.total_citations == 1
        assert coverage.verified_citations == 0
        assert coverage.unverified_citations == 1
        assert "cite_orphan" in coverage.unverified_ids
        assert coverage.coverage_ratio == 0.0

    def test_citation_coverage_no_chain(self) -> None:
        """No provenance chain yields perfect coverage (vacuously true)."""
        record = _make_record()
        reporter = GlassBoxReporter()
        coverage = reporter.verify_citation_coverage(record=record)

        assert coverage.coverage_ratio == 1.0
        assert coverage.total_citations == 0

    def test_quality_metrics_with_provenance(self) -> None:
        """Quality metrics include provenance stats when chain is present."""
        link = _make_link("llm_1", sources=(_make_source("src_a"),), citation_ids=("cite_1",))
        chain = ProvenanceChain(run_id=RunID("run_001"), links=(link,))
        record = _make_record(chain=chain, success=True)
        record.llm_calls = [_make_llm_call("llm_1")]

        reporter = GlassBoxReporter()
        report = reporter.generate(record=record)

        assert report.quality_metrics["provenance_links"] == 1
        assert report.quality_metrics["unique_sources"] == 1
        assert report.quality_metrics["total_citations"] == 1
        assert report.quality_metrics["run_success"] is True

    def test_report_to_dict_roundtrip(self) -> None:
        """Report serializes to dictionary cleanly."""
        link = _make_link("llm_1", node_id="step_0", sources=(_make_source("src_a"),))
        chain = ProvenanceChain(run_id=RunID("run_001"), links=(link,))
        calls = [_make_llm_call("llm_1", node_id="step_0")]
        record = _make_record(llm_calls=calls, chain=chain, total_cost_usd=0.01)

        reporter = GlassBoxReporter()
        report = reporter.generate(record=record)
        d = report.to_dict()

        assert d["run_id"] == "run_001"
        assert d["provenance_chain"] is not None
        assert "decision_trace" in d
        assert "token_audit" in d
        assert "cost_breakdown" in d
        assert "citation_coverage" in d
        assert "quality_metrics" in d

    def test_multi_link_provenance(self) -> None:
        """Report handles multiple provenance links correctly."""
        src_a = _make_source("src_a", token_count=500)
        src_b = _make_source("src_b", token_count=300)
        src_c = _make_source("src_c", token_count=200, included=False, exclusion_reason=ExclusionReason.STALE)

        link1 = _make_link(
            "llm_1",
            node_id="step_0",
            agent_id="librarian",
            sources=(src_a, src_c),
            cost_usd=0.05,
        )
        link2 = _make_link("llm_2", node_id="step_1", agent_id="summarizer", sources=(src_b,), cost_usd=0.03)

        chain = ProvenanceChain(run_id=RunID("run_001"), links=(link1, link2))
        calls = [
            _make_llm_call("llm_1", node_id="step_0", agent_id="librarian", cost_usd=0.05),
            _make_llm_call("llm_2", node_id="step_1", agent_id="summarizer", cost_usd=0.03),
        ]
        record = _make_record(llm_calls=calls, chain=chain, total_cost_usd=0.08)

        reporter = GlassBoxReporter()
        report = reporter.generate(record=record)

        assert len(report.decision_trace) == 2
        assert report.token_audit.sources_included == 2
        assert report.token_audit.sources_excluded == 1
        assert report.token_audit.exclusion_reasons["stale"] == 1
        assert report.cost_breakdown.by_node["step_0"] == pytest.approx(0.05)
        assert report.cost_breakdown.by_node["step_1"] == pytest.approx(0.03)


class TestGlassBoxModels:
    """Tests for Glass Box data models."""

    def test_cost_breakdown_to_dict(self) -> None:
        cb = CostBreakdown(
            total_cost_usd=0.5,
            by_model={"gpt-4o": 0.5},
            by_node={"step_0": 0.5},
            by_agent={"lib": 0.5},
        )
        d = cb.to_dict()
        assert d["total_cost_usd"] == 0.5
        assert d["by_model"]["gpt-4o"] == 0.5

    def test_token_audit_to_dict(self) -> None:
        ta = TokenAudit(
            total_input_tokens=100,
            total_output_tokens=50,
            by_node={},
            by_agent={},
            by_source={"s1": 100},
            sources_included=1,
            sources_excluded=0,
            exclusion_reasons={},
        )
        d = ta.to_dict()
        assert d["total_input_tokens"] == 100
        assert d["by_source"]["s1"] == 100

    def test_citation_coverage_to_dict(self) -> None:
        cc = CitationCoverage(
            total_citations=3,
            verified_citations=2,
            unverified_citations=1,
            coverage_ratio=2 / 3,
            unverified_ids=("c3",),
        )
        d = cc.to_dict()
        assert d["total_citations"] == 3
        assert d["unverified_ids"] == ["c3"]
