"""Machine-proven traceability: every node in a run is fully traced.

The glassbox_trace example reconstructs a per-step trace from CEMAF's audit
trail, context-patch provenance, citations, and node timing. This test asserts
the enforceable form of the "99.99% traceability" claim: EVERY node in a real
run has a per-step audit record AND timing — no black-box steps.

It also pins the framework fix that made this possible: the audit subscriber
now maps TASK_COMPLETED/TASK_FAILED → NODE_EXECUTED, so per-node executions
actually land in the trail (previously only DAG-level events did).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from cemaf.audit.models import AuditEntryType

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "glassbox_trace.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("glassbox_trace", _EXAMPLE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register before exec so frozen dataclasses with stringized annotations
    # resolve cls.__module__ in sys.modules (Python 3.14 dataclass requirement).
    sys.modules["glassbox_trace"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_every_node_is_fully_traced() -> None:
    """100% per-node coverage: each node has an audit event + timing."""
    example = _load_example()
    result, audit_log, citation_tracker = await example.run_traced(use_otel=False)
    trace = await example.build_trace(result=result, audit_log=audit_log, citation_tracker=citation_tracker)

    assert trace.status == "completed"
    assert trace.coverage["total_nodes"] == 3
    # The headline claim: no node is a black box.
    assert trace.coverage["fully_traced"] is True
    assert trace.coverage["nodes_with_audit_events"] == trace.coverage["total_nodes"]
    assert trace.coverage["nodes_with_timing"] == trace.coverage["total_nodes"]

    # Each step carries a per-node audit record.
    for step in trace.steps:
        assert step.audit_events, f"node {step.node_id} has no audit events — black box"
        assert AuditEntryType.NODE_EXECUTED.value in step.audit_events


@pytest.mark.asyncio
async def test_trace_captures_decisions_provenance_and_citations() -> None:
    """The trace surfaces WHAT was decided, WHY context changed, and source citations."""
    example = _load_example()
    result, audit_log, citation_tracker = await example.run_traced(use_otel=False)
    trace = await example.build_trace(result=result, audit_log=audit_log, citation_tracker=citation_tracker)

    steps = {s.node_id: s for s in trace.steps}

    # Auction decision is recorded with the winner + score.
    assert "selection" in steps["summarize"].decision
    assert steps["summarize"].decision["selection"]["agent_id"] in {"SummarizerIdle", "SummarizerBusy"}

    # Council decision records the full ballot set (every vote is visible).
    council = steps["review"].decision["council"]
    assert council["winning_choice"] == "approve"
    assert len(council["ballots"]) == 3

    # Context provenance: every produced key names its source node + reason.
    prov_paths = {p["path"] for p in trace.context_provenance}
    assert {"facts", "summary", "verdict"} <= prov_paths
    for prov in trace.context_provenance:
        assert prov["reason"], "every context change must carry a reason"

    # Citation: comes from the REAL CitationTracker registry (has a generated
    # citation_id), not a hand-pasted dict. The tracker also holds a cited fact
    # binding the Researcher's output to that source.
    assert trace.citations, "no citations registered"
    cite = trace.citations[0]
    assert cite["citation_id"].startswith("cite")
    assert cite["source_id"] == "doc.cemaf_design#traceability"
    assert citation_tracker.get_all_citations(), "tracker registry is empty"
    assert citation_tracker.get_cited_facts(), "no cited fact bound to a source"


@pytest.mark.asyncio
async def test_audit_subscriber_records_per_node_task_events() -> None:
    """Regression: TASK_COMPLETED must produce per-node NODE_EXECUTED audit entries."""
    example = _load_example()
    result, audit_log, _tracker = await example.run_traced(use_otel=False)

    entries = await audit_log.query(run_id=str(result.run_id), limit=500)
    node_executed = [e for e in entries if e.type == AuditEntryType.NODE_EXECUTED]
    # One per node (research, summarize, review).
    node_ids = {str(e.payload.get("node_id")) for e in node_executed}
    assert {"research", "summarize", "review"} <= node_ids


@pytest.mark.asyncio
async def test_audit_trail_records_node_decisions() -> None:
    """The audit trail itself (not just NodeResult.metadata) carries decisions.

    Before the fix, auction/council verdicts lived only in NodeResult.metadata
    and the audit trail was blind to them. Now the executor writes decision
    metadata into the TASK_COMPLETED payload, so NODE_EXECUTED entries record
    WHAT each node decided.
    """
    example = _load_example()
    result, audit_log, _tracker = await example.run_traced(use_otel=False)

    entries = await audit_log.query(run_id=str(result.run_id), limit=500)
    by_node = {
        str(e.payload.get("node_id")): e.payload for e in entries if e.type == AuditEntryType.NODE_EXECUTED
    }

    # Auction decision is in the audit payload for the summarize node.
    assert "selection" in by_node["summarize"]
    assert by_node["summarize"]["selection"]["agent_id"] in {"SummarizerIdle", "SummarizerBusy"}

    # Council verdict + ballots are in the audit payload for the review node.
    assert "council" in by_node["review"]
    assert by_node["review"]["council"]["winning_choice"] == "approve"
    assert len(by_node["review"]["council"]["ballots"]) == 3
