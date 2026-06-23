"""Glassbox per-step traceability for one DAG run.

Reconstructs a complete, per-step trace of a run from CEMAF's own observability
surfaces — no black-box steps, every node accounted for with what it did, what
it decided, why, what it cited, and how long it took:

  - AuditTrail        → every node/eval event, keyed by run_id, now carrying the
                        node's decision metadata (auction winner, council verdict)
  - Context.patches   → ContextPatch provenance: which node wrote each key
  - CitationTracker   → the real citation subsystem: source-id + confidence per
                        retrieved claim, plus the cited-fact binding
  - NodeResult        → per-node decision metadata + the agent's own `reasoning`
  - Tracer (optional) → OTel spans, exported when `--otel` is passed

Scope/honesty: the demo agents are deterministic (no live LLM), so "reasoning"
is each agent's recorded rationale string, not chain-of-thought from a model.
With real LLM agents the same `reasoning` field carries their actual rationale —
the trace plumbing is identical. This proves the framework captures per-step
provenance; it is not a claim about model cognition.

Three outputs:
  1. A human-readable step-by-step transcript (default).
  2. A structured JSON trace artifact (--json PATH) — machine-checkable.
  3. OTel spans (--otel) — view in a real tracer.

Run:
    uv run python examples/glassbox_trace.py
    uv run python examples/glassbox_trace.py --json /tmp/trace.json
    uv run python examples/glassbox_trace.py --otel        # needs cemaf[otel]

build_trace() is imported by tests/integration/test_glassbox_trace.py, which
asserts EVERY node has an audit record AND positive timing — machine-proven
per-step coverage.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from cemaf.agents.base import AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.agents.selection import Capability, DefaultAgentSelector
from cemaf.audit.factories import create_audit_system
from cemaf.audit.protocols import AuditLog
from cemaf.bootstrap import create_executor
from cemaf.citation.tracker import CitationTracker
from cemaf.context.patch import PatchOperation, PatchSource
from cemaf.core.types import JSON, AgentID, NodeID
from cemaf.council.aggregator import DefaultVoteAggregator
from cemaf.council.types import Opinion
from cemaf.evals.evaluators import LengthEvaluator
from cemaf.events.bus import InMemoryEventBus
from cemaf.interceptors import create_interceptor_pipeline
from cemaf.interceptors.gate_eval import GateEvalInterceptor, GateFailureMode
from cemaf.orchestration.dag import DAG, Edge, Node
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.results import ExecutionResult
from cemaf.orchestration.services import RuntimeServices
from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider
from cemaf.retrieval.protocols import Document, VectorStore

# ---------------------------------------------------------------------------
# Demo agents — each one records WHY it pulled the context it used, so the
# trace can show provenance, not just inputs.
# ---------------------------------------------------------------------------


class _ResearchGoal(BaseModel):
    topic: str = "CEMAF traceability"


class Researcher:
    """Retrieves a fact from a real vector store and cites it via the real
    CitationTracker subsystem — no hand-pasted citation dicts."""

    def __init__(self, *, vector_store: VectorStore, citation_tracker: CitationTracker) -> None:
        self._id = AgentID("TraceResearcher")
        self._vector_store = vector_store
        self._citations = citation_tracker

    @property
    def id(self) -> AgentID:
        return self._id

    @property
    def description(self) -> str:
        return "Retrieves a fact and cites its source."

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _ResearchGoal, context: AgentContext) -> AgentResult[str]:
        # Real retrieval against the seeded vector store.
        results = await self._vector_store.search_by_text(query_text=goal.topic, k=1)
        if not results:
            return AgentResult.fail(error="no source found for topic", state=AgentState())

        top = results[0]
        fact = top.document.content
        # Real citation: register the SearchResult, then bind the fact to it.
        citation = self._citations.track_search_result(top)
        self._citations.create_cited_fact(fact=fact, citations=[citation], confidence=top.score)

        reasoning = (
            f"Searched the store for '{goal.topic}'; top hit "
            f"'{top.document.id}' scored {top.score:.2f}, above other matches, "
            "so I returned its content as the grounded fact."
        )
        return AgentResult.ok(
            output=fact,
            state=AgentState(),
            metadata={"cost_estimate_usd": 0.01, "reasoning": reasoning},
        )


class _WriteGoal(BaseModel):
    facts: str = ""
    objective: str = "Summarize the fact in one sentence."


class Summarizer:
    """WRITE-capable; chosen by auction on load."""

    def __init__(self, agent_id: str, *, load: float) -> None:
        self._id = AgentID(agent_id)
        self._load = load

    @property
    def id(self) -> AgentID:
        return self._id

    @property
    def description(self) -> str:
        return "Summarizes facts into a one-line answer."

    @property
    def skills(self) -> tuple[()]:
        return ()

    @property
    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.WRITE})

    @property
    def current_load(self) -> float:
        return self._load

    async def run(self, goal: _WriteGoal, context: AgentContext) -> AgentResult[str]:
        summary = (
            "CEMAF is glassbox: every step is auditable, cited, and provenance-tracked "
            f"(based on: {goal.facts[:60]}...)."
        )
        reasoning = (
            f"Condensed the {len(goal.facts.split())}-word research fact into a "
            "single grounded sentence, preserving the auditable/cited/provenance claim."
        )
        return AgentResult.ok(
            output=summary,
            state=AgentState(),
            metadata={
                "cost_estimate_usd": 0.02,
                "tokens_total": len(summary.split()),
                "overall_score": 0.95,
                "reasoning": reasoning,
            },
        )


class _ReviewGoal(BaseModel):
    objective: str = "Approve the summary?"


class Reviewer:
    """Council member."""

    def __init__(self, member_id: str, vote: str, rationale: str = "") -> None:
        self._id = AgentID(member_id)
        self._vote = vote
        self._rationale = rationale

    @property
    def id(self) -> AgentID:
        return self._id

    @property
    def description(self) -> str:
        return "Votes to approve or reject."

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _ReviewGoal, context: AgentContext) -> AgentResult[str]:
        return AgentResult.ok(output=self._vote, state=AgentState())

    async def deliberate(self, *, question: object, goal: object, context: AgentContext) -> Opinion:
        return Opinion(member_id=self._id, choice=self._vote, rationale=self._rationale)


# ---------------------------------------------------------------------------
# Trace model + builder (imported by the coverage test)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StepTrace:
    """Everything we know about one DAG node."""

    node_id: str
    success: bool
    duration_ms: float
    decision: JSON  # auction/council/gate metadata — WHAT it decided
    reasoning: str  # the agent's own rationale — WHY it produced this output
    audit_events: tuple[str, ...]  # audit entry types attributed to this run step
    output_preview: str


@dataclass(frozen=True)
class RunTrace:
    """The full glassbox trace for one run."""

    run_id: str
    status: str
    steps: tuple[StepTrace, ...]
    context_provenance: tuple[JSON, ...]  # ContextPatch records: who/why context changed
    citations: tuple[JSON, ...]
    audit_total: int
    coverage: JSON = field(default_factory=dict)

    def to_dict(self) -> JSON:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "steps": [
                {
                    "node_id": s.node_id,
                    "success": s.success,
                    "duration_ms": s.duration_ms,
                    "decision": s.decision,
                    "reasoning": s.reasoning,
                    "audit_events": list(s.audit_events),
                    "output_preview": s.output_preview,
                }
                for s in self.steps
            ],
            "context_provenance": list(self.context_provenance),
            "citations": list(self.citations),
            "audit_total": self.audit_total,
            "coverage": self.coverage,
        }


async def build_trace(
    *,
    result: ExecutionResult,
    audit_log: AuditLog,
    citation_tracker: CitationTracker | None = None,
) -> RunTrace:
    """Reconstruct a complete per-step trace from CEMAF's observability surfaces."""
    run_id = str(result.run_id)
    audit_entries = await audit_log.query(run_id=run_id, limit=500)
    # Audit events grouped by their node (audit payloads carry node_id when present),
    # plus the decision metadata the executor now writes into the audit event so the
    # trail itself records WHAT each node decided.
    events_by_node: dict[str, list[str]] = {}
    audit_decisions_by_node: dict[str, JSON] = {}
    for entry in audit_entries:
        node_id = str(entry.payload.get("node_id", ""))
        events_by_node.setdefault(node_id, []).append(entry.type.value)
        for key in ("council", "selection", "auction", "gate"):
            if key in entry.payload:
                audit_decisions_by_node.setdefault(node_id, {})[key] = entry.payload[key]

    steps: list[StepTrace] = []
    for node_result in result.node_results:
        nid = str(node_result.node_id)
        # Prefer decisions reconstructed from the AUDIT TRAIL (proves the trail
        # captured them); fall back to NodeResult.metadata if absent.
        decision: JSON = dict(audit_decisions_by_node.get(nid, {}))
        for key in ("council", "selection", "auction", "gate", "recovery"):
            if key not in decision and key in node_result.metadata:
                decision[key] = node_result.metadata[key]
        # The agent's own rationale, if it recorded one in its result metadata.
        reasoning = str(node_result.metadata.get("reasoning", ""))
        steps.append(
            StepTrace(
                node_id=nid,
                success=node_result.success,
                duration_ms=node_result.duration_ms,
                decision=decision,
                reasoning=reasoning,
                audit_events=tuple(events_by_node.get(nid, ())),
                output_preview=str(node_result.output)[:80],
            )
        )

    # Context provenance: every ContextPatch carries who/why/correlation.
    provenance: list[JSON] = []
    for patch in result.final_context.patch_history:
        provenance.append(
            {
                "path": patch.path,
                "operation": patch.operation.value
                if isinstance(patch.operation, PatchOperation)
                else str(patch.operation),
                "source": patch.source.value if isinstance(patch.source, PatchSource) else str(patch.source),
                "source_id": patch.source_id,
                "reason": patch.reason,
                "correlation_id": patch.correlation_id,
            }
        )

    # Citations from the real CitationTracker registry — each is a Citation the
    # Researcher registered from an actual SearchResult, not a hand-pasted dict.
    citations: list[JSON] = []
    if citation_tracker is not None:
        for citation in citation_tracker.get_all_citations():
            citations.append(
                {
                    "citation_id": citation.id,
                    "source_id": citation.source_id,
                    "source_type": citation.source_type,
                    "title": citation.title,
                    "confidence": citation.confidence,
                }
            )

    nodes_with_audit = sum(1 for s in steps if s.audit_events)
    # A node that actually executed records a positive wall-clock duration. The
    # old `>= 0` check was tautological (the default is 0.0); `> 0` proves the
    # node really ran and was timed.
    nodes_with_timing = sum(1 for s in steps if s.duration_ms > 0)
    nodes_with_reasoning = sum(1 for s in steps if s.reasoning)
    coverage = {
        "total_nodes": len(steps),
        "nodes_with_audit_events": nodes_with_audit,
        "nodes_with_timing": nodes_with_timing,
        "nodes_with_reasoning": nodes_with_reasoning,
        # Every node has a per-step audit record AND real (positive) timing.
        "fully_traced": (
            len(steps) > 0 and nodes_with_audit == len(steps) and nodes_with_timing == len(steps)
        ),
    }

    return RunTrace(
        run_id=run_id,
        status=result.status.value,
        steps=tuple(steps),
        context_provenance=tuple(provenance),
        citations=tuple(citations),
        audit_total=len(audit_entries),
        coverage=coverage,
    )


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def _build_dag() -> DAG:
    return DAG(
        name="glassbox-trace",
        nodes=(
            Node.agent(id="research", name="Research", agent_id="TraceResearcher", output_key="facts"),
            Node.auction(
                id="summarize",
                name="Summarize",
                capability=Capability.WRITE.value,
                input_mapping={"facts": "facts"},
                output_key="summary",
            ),
            Node.council(
                id="review",
                name="Review",
                members=("rev_a", "rev_b", "rev_c"),
                options=("approve", "reject"),
                output_key="verdict",
            ),
        ),
        edges=(
            Edge(source=NodeID("research"), target=NodeID("summarize")),
            Edge(source=NodeID("summarize"), target=NodeID("review")),
        ),
        entry_node=NodeID("research"),
    )


async def run_traced(*, use_otel: bool = False) -> tuple[ExecutionResult, AuditLog, CitationTracker]:
    event_bus = InMemoryEventBus()
    audit_log, _audit_trail = create_audit_system(event_bus=event_bus)

    # Real retrieval source + real citation tracker for the Researcher.
    vector_store = InMemoryVectorStore(embedding_provider=MockEmbeddingProvider(dimension=64))
    await vector_store.add(
        Document(
            id="doc.cemaf_design#traceability",
            content=(
                "CEMAF reconstructs a per-step trace from its audit trail, context "
                "patch provenance, citations, and node timing."
            ),
            metadata={"title": "CEMAF Design — Traceability", "namespace": "design"},
        )
    )
    citation_tracker = CitationTracker(event_bus=event_bus)

    registry = AgentRegistry()
    registry.register_agent(
        agent_instance=Researcher(vector_store=vector_store, citation_tracker=citation_tracker),
        goal_type=_ResearchGoal,
    )
    registry.register_agent(
        agent_instance=Summarizer("SummarizerBusy", load=0.9),
        goal_type=_WriteGoal,
        capabilities=frozenset({Capability.WRITE}),
    )
    registry.register_agent(
        agent_instance=Summarizer("SummarizerIdle", load=0.1),
        goal_type=_WriteGoal,
        capabilities=frozenset({Capability.WRITE}),
    )
    reviewers = (
        ("rev_a", "approve", "Summary is accurate and grounded in the cited fact."),
        ("rev_b", "approve", "Concise and preserves the auditable/cited claim."),
        ("rev_c", "reject", "Wants the source title named inline before shipping."),
    )
    for member_id, vote, rationale in reviewers:
        registry.register_instance(item=Reviewer(member_id, vote, rationale))

    tracer = None
    if use_otel:
        # Best-effort: needs cemaf[otel] AND an OTLP collector at localhost:4317.
        # Spans export there; without a collector the run still completes, you
        # just won't see spans. The text/JSON trace below is collector-free.
        try:
            from opentelemetry import trace as _otel_trace

            from cemaf.observability.otel_setup import configure_otel
            from cemaf.observability.otel_tracer import OTelTracer

            configure_otel(service_name="cemaf-glassbox-trace")
            tracer = OTelTracer(tracer=_otel_trace.get_tracer("cemaf-glassbox-trace"))
            print("OTel configured — spans export to OTLP at localhost:4317")
        except ImportError:
            print("--otel requested but cemaf[otel] not installed; continuing without spans")

    interceptor_pipeline = create_interceptor_pipeline(
        interceptors=(
            GateEvalInterceptor(
                evaluators=(LengthEvaluator(min_length=20),),
                node_pattern="summarize",
                threshold=0.5,
                on_failure=GateFailureMode.RECOVER,
            ),
        ),
    )

    executor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=True),
        services=RuntimeServices(
            event_bus=event_bus,
            agent_selector=DefaultAgentSelector(),
            council_aggregator=DefaultVoteAggregator(),
            interceptor_pipeline=interceptor_pipeline,
            tracer=tracer,
        ),
    )
    result = await executor.run(dag=_build_dag())
    return result, audit_log, citation_tracker


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _print_transcript(trace: RunTrace) -> None:
    print("\n" + "=" * 78)
    print("CEMAF GLASSBOX TRACE — see inside the agents' minds")
    print("=" * 78)
    print(f"run_id : {trace.run_id}")
    print(f"status : {trace.status}")
    print(f"audit events recorded : {trace.audit_total}\n")

    print("--- per-step trace (what each agent did, decided, how long) ---")
    for i, step in enumerate(trace.steps, start=1):
        print(f"\n  STEP {i}: node='{step.node_id}'  success={step.success}  {step.duration_ms:.2f}ms")
        if step.reasoning:
            print(f"    reasoning    : {step.reasoning}")
        if step.decision:
            for key, val in step.decision.items():
                print(f"    decision[{key}]: {val}")
        print(f"    audit events : {', '.join(step.audit_events) or '—'}")
        print(f"    output       : {step.output_preview}")

    print("\n--- context provenance (who pulled what, and WHY) ---")
    if trace.context_provenance:
        for prov in trace.context_provenance:
            src = f"{prov['source']}/{prov['source_id']}"
            print(f"    path='{prov['path']}'  source={src}  reason='{prov['reason']}'")
    else:
        print("    (no explicit ContextPatch provenance in this run)")

    print("\n--- citations (real CitationTracker registry) ---")
    if trace.citations:
        for cite in trace.citations:
            print(
                f"    id={cite.get('citation_id')}  source={cite.get('source_id')}  "
                f"title='{cite.get('title')}'  confidence={cite.get('confidence')}"
            )
    else:
        print("    (no citations attached)")

    print("\n--- traceability coverage ---")
    for key, val in trace.coverage.items():
        print(f"    {key}: {val}")
    print()


async def main() -> None:
    parser = argparse.ArgumentParser(description="CEMAF glassbox trace demo")
    parser.add_argument("--json", type=Path, default=None, help="write structured trace JSON here")
    parser.add_argument(
        "--otel", action="store_true", help="export OTel spans to console (needs cemaf[otel])"
    )
    args = parser.parse_args()

    result, audit_log, citation_tracker = await run_traced(use_otel=args.otel)
    trace = await build_trace(result=result, audit_log=audit_log, citation_tracker=citation_tracker)

    _print_transcript(trace)

    if args.json is not None:
        args.json.write_text(json.dumps(trace.to_dict(), indent=2, default=str))
        print(f"structured trace written → {args.json}")


if __name__ == "__main__":
    asyncio.run(main())
