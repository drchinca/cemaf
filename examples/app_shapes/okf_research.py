"""Offline research memory: discover → read → cite → gate → propose.

Run: uv run python examples/app_shapes/okf_research.py
Keep a reviewable bundle: append --proposal-dir /tmp/research-proposal
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from pydantic import BaseModel

from cemaf import DAG, Agent, AgentContext, AgentRegistry, AgentResult, AgentState, Node, create_executor
from cemaf.citation import CitationTracker
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
from cemaf.core.types import JSON, AgentID
from cemaf.evals.grounding import GroundednessEvaluator
from cemaf.evals.protocols import EvalResult
from cemaf.events.bus import InMemoryEventBus
from cemaf.ingestion import OKFAdapter
from cemaf.interceptors.gate_eval import GateEvalInterceptor
from cemaf.interceptors.pipeline import InterceptorPipeline
from cemaf.knowledge import OKFBundle, OKFDocument, create_knowledge_graph, import_okf_bundle
from cemaf.memory.factories import create_memory_manager
from cemaf.observability.run_logger import InMemoryRunLogger
from cemaf.orchestration.services import RuntimeServices
from cemaf.retrieval.protocols import SearchResult

BUNDLE_PATH = Path(__file__).resolve().parents[1] / "data" / "okf_research"


class ResearchGoal(BaseModel):
    content: str
    path: str
    bundle_id: str
    revision: str


class ResearchAgent(Agent[ResearchGoal, JSON]):
    @property
    def id(self) -> AgentID:
        return AgentID("okf-researcher")

    @property
    def description(self) -> str:
        return "Cite a selected finding and propose a review note."

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: ResearchGoal, context: AgentContext) -> AgentResult[JSON]:
        document = OKFDocument.parse(path=goal.path, text=goal.content)
        source = document.to_document(bundle_id=goal.bundle_id, revision=goal.revision)
        assert context.knowledge_graph is not None
        entity = await context.knowledge_graph.get_entity(source.id)
        assert entity is not None and entity.properties["content_hash"] == document.content_hash
        assert any(goal.content in message["content"] for message in context.artifacts["compiled_context"])

        # Deterministic offline extraction. A real research agent can use its LLM
        # here while retaining the same context, citation, and evaluation path.
        answer = document.body.strip().splitlines()[0]
        tracker = CitationTracker()
        citation = tracker.track_search_result(SearchResult(document=source, score=1.0))
        fact = tracker.create_cited_fact(fact=answer, citations=[citation])
        proposal = document.propose(
            body=document.body + "\n## Review note\n\nThe finding was retrieved for a research report.\n",
            actor="cemaf/okf-researcher",
            run_id=context.run_id,
        )
        return AgentResult.ok(
            output={"answer": fact.fact, "citation": citation.to_dict(), "proposal": proposal.render()},
            state=AgentState(),
        )


class ResearchEvidenceEval(GroundednessEvaluator):
    """Bind the existing evaluator to this example's selected source and output."""

    def __init__(self, document: OKFDocument, *, bundle_id: str, revision: str) -> None:
        super().__init__()
        self.document = document
        self.bundle_id = bundle_id
        self.revision = revision

    async def evaluate(
        self, output: Any, expected: Any | None = None, context: JSON | None = None
    ) -> EvalResult:
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except ValueError:
                return self._make_result(score=0.0, reason="Research output must be JSON")
        if (
            not isinstance(output, dict)
            or not isinstance(output.get("answer"), str)
            or not output["answer"].strip()
        ):
            return self._make_result(score=0.0, reason="Research output requires a non-empty answer")
        citation = output.get("citation", {})
        if not isinstance(citation, dict):
            return self._make_result(score=0.0, reason="Citation must be an object")
        metadata = citation.get("metadata", {})
        if (
            not isinstance(metadata, dict)
            or citation.get("source_id") != self.document.source_id(bundle_id=self.bundle_id)
            or metadata.get("content_hash") != self.document.content_hash
            or metadata.get("bundle_revision") != self.revision
        ):
            return self._make_result(score=0.0, reason="Citation does not identify the selected revision")
        return await super().evaluate(
            output=output.get("answer", ""), context={"grounding_sources": [self.document.body]}
        )


async def run_example(proposal_dir: Path) -> JSON:
    bundle = OKFBundle.load(BUNDLE_PATH)
    revision = bundle.revision
    # Discovery yields a concept ID; only this concept enters the agent prompt.
    selected = bundle.get("findings/calibration")
    bundle_id = "research"
    estimator = SimpleTokenEstimator()
    budget = TokenBudget(max_tokens=2400, reserved_for_output=400)
    adapter = OKFAdapter(bundle_id=bundle_id, revision=revision)
    discovery_budget = TokenBudget(max_tokens=200, reserved_for_output=0)
    discovery = await adapter.adapt_catalog(bundle, discovery_budget, directory="findings")
    print(discovery.source.content)
    source = await adapter.adapt(selected, budget)
    graph = create_knowledge_graph(create_memory_manager())
    imported = await import_okf_bundle(bundle, graph=graph, bundle_id=bundle_id)
    assert not imported.unresolved_links
    logger = InMemoryRunLogger()
    services = RuntimeServices(
        knowledge_graph=graph,
        context_compiler=PriorityContextCompiler(estimator),
        token_budget=budget,
        event_bus=InMemoryEventBus(),
        run_logger=logger,
        interceptor_pipeline=InterceptorPipeline(
            interceptors=(
                GateEvalInterceptor(
                    evaluators=(ResearchEvidenceEval(selected, bundle_id=bundle_id, revision=revision),),
                    threshold=1.0,
                ),
            )
        ),
    )
    registry = AgentRegistry()
    registry.register_agent(agent_instance=ResearchAgent(), goal_type=ResearchGoal)
    dag = DAG(name="okf-research").add_node(
        Node.agent(
            id="research",
            name="Research",
            agent_id="okf-researcher",
            output_key="report",
            input_mapping={
                "content": source.content,
                "path": selected.path,
                "bundle_id": bundle_id,
                "revision": revision,
            },
        )
    )
    result = await create_executor(agent_registry=registry, services=services).run(dag=dag)
    assert result.success, result.error
    report = result.final_context.get("report")
    if isinstance(report, str):
        report = json.loads(report)
    proposal = OKFDocument.parse(path=selected.path, text=report["proposal"])
    assert proposal.trust_tier == "unverified"
    assert proposal.frontmatter["cemaf_proposal"]["run_id"] == str(result.run_id)
    assert proposal.proposal_matches(selected)
    proposed_bundle = bundle.with_document(proposal)
    changes = proposed_bundle.diff(bundle)
    assert changes.modified == (selected.concept_id,)
    proposed_bundle.write(proposal_dir)
    assert OKFBundle.load(BUNDLE_PATH).revision == revision
    record = logger.get_record(str(result.run_id))
    assert record is not None and record.patches
    assert result.node_results[0].metadata["interceptors"]["gate_eval:*"]["gate"] == "passed"
    print(f"Answer: {report['answer']}")
    print(f"Selected concept: {source.token_count} estimated tokens")
    print(f"Reviewable proposal: {proposal_dir}")
    return {**report, "run_id": str(result.run_id), "revision": revision}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal-dir", type=Path)
    args = parser.parse_args()
    if args.proposal_dir:
        await run_example(args.proposal_dir)
    else:
        with TemporaryDirectory(prefix="cemaf-okf-") as directory:
            await run_example(Path(directory) / "proposal")


if __name__ == "__main__":
    asyncio.run(main())
