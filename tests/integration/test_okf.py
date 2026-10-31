"""OKF uses the real CEMAF graph, context compiler, retrieval, and citation path."""

from pathlib import Path

import pytest

from cemaf.citation import CitationTracker
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
from cemaf.ingestion import OKFAdapter
from cemaf.knowledge import EntityType, OKFBundle, OKFDocument, RelationType, create_knowledge_graph
from cemaf.knowledge.okf_graph import import_okf_bundle
from cemaf.memory.factories import create_memory_manager
from cemaf.retrieval.factories import create_in_memory_vector_store


async def test_okf_graph_context_retrieval_citation_and_proposal(tmp_path: Path) -> None:
    document = OKFDocument(
        path="findings/measurement.md",
        frontmatter={
            "type": "Novel Scientific Entity",
            "title": "Measured result",
            "sources": [{"resource": "../protocols/method.md"}],
        },
        body="Measured repeatability is 0.02 units. See [method](/protocols/method.md).\n"
        "See [future work](./future.md).",
    )
    method = OKFDocument(path="protocols/method.md", frontmatter={"type": "Procedure"}, body="Ten readings.")
    bundle = OKFBundle((document, method))
    graph = create_knowledge_graph(create_memory_manager())
    imported = await import_okf_bundle(bundle, graph=graph, bundle_id="experiment")
    assert imported.entity_count == 2
    assert imported.relation_count == 2
    assert imported.unresolved_links == (("findings/measurement", "./future.md"),)
    entity = await graph.get_entity(document.source_id(bundle_id="experiment"))
    assert entity is not None and entity.type == EntityType.CONCEPT
    assert entity.properties["okf_type"] == "Novel Scientific Entity"
    neighbors = await graph.query_neighbors(entity.id)
    assert {relation.type for relation in neighbors.relations} == {
        RelationType.REFERENCES,
        RelationType.EXTRACTED_FROM,
    }
    assert {neighbor.name for neighbor in neighbors.entities} == {"method"}
    with pytest.raises(ValueError, match="unused namespace"):
        await import_okf_bundle(bundle, graph=graph, bundle_id="experiment")

    store = create_in_memory_vector_store()
    await store.add_batch(
        [doc.to_document(bundle_id="experiment", revision=bundle.revision) for doc in bundle.documents]
    )
    results = await store.search_by_text("Measured repeatability", k=2)
    tracker = CitationTracker()
    citations = tracker.track_search_results(results)
    assert all(c.metadata["bundle_revision"] == bundle.revision for c in citations)
    assert {c.metadata["content_hash"] for c in citations} == {document.content_hash, method.content_hash}
    assert all(c.source_type == "okf" for c in citations)

    estimator = SimpleTokenEstimator()
    adapter = OKFAdapter(bundle_id="experiment", revision=bundle.revision, token_estimator=estimator)
    budget = TokenBudget(max_tokens=adapter.estimate_tokens(document), reserved_for_output=0)
    source = await adapter.adapt(document, budget, priority=100)
    compiler = PriorityContextCompiler(estimator)
    compiled = await compiler.compile(
        artifacts=((source.key, source.content), ("oversize", "Unrelated history " * 1000)),
        memories=(),
        budget=budget,
        priorities={source.key: 100},
    )
    assert compiled.within_budget()
    assert [item.key for item in compiled.sources] == [source.key]
    assert compiled.sources[0].content == document.render()

    original = bundle.write(tmp_path / "accepted")
    proposal = document.propose(body=document.body + "\nReview requested.\n", actor="cemaf/test", run_id="r1")
    destination = bundle.with_document(proposal).write(tmp_path / "proposal")
    assert OKFBundle.load(original).revision == imported.revision
    assert (
        OKFBundle.load(destination).get(document.concept_id).frontmatter["cemaf_proposal"]["run_id"] == "r1"
    )


async def test_offline_research_dag_and_reviewable_export(tmp_path: Path) -> None:
    from examples.app_shapes.okf_research import BUNDLE_PATH, ResearchEvidenceEval, run_example

    report = await run_example(tmp_path / "proposal")
    bundle = OKFBundle.load(BUNDLE_PATH)
    selected = bundle.get("findings/calibration")
    assert report["citation"]["metadata"]["content_hash"] == selected.content_hash
    proposal = OKFBundle.load(tmp_path / "proposal").get(selected.concept_id)
    assert proposal.frontmatter["cemaf_proposal"]["run_id"] == report["run_id"]
    evaluator = ResearchEvidenceEval(selected, bundle_id="research", revision=bundle.revision)
    # A supported answer still fails if it cites a different snapshot.
    report["citation"]["metadata"]["bundle_revision"] = "wrong-revision"
    assert not (await evaluator.evaluate(report)).passed


async def test_two_persisted_sessions_embed_only_changed_concepts(tmp_path: Path) -> None:
    from cemaf.retrieval.memory_store import MockEmbeddingProvider
    from examples.app_shapes.okf_project_memory import run_sessions

    class CountingEmbeddings(MockEmbeddingProvider):
        def __init__(self) -> None:
            super().__init__()
            self.inputs: list[str] = []

        async def embed(self, text: str) -> tuple[float, ...]:
            self.inputs.append(text)
            return await super().embed(text)

    provider = CountingEmbeddings()
    result = await run_sessions(tmp_path, embedding_provider=provider)
    assert result["initial_count"] == 3
    assert result["changed_count"] == 2
    assert result["removed_count"] == 1
    # Three first-session docs, two changed docs, and one search query.
    assert len(provider.inputs) == 6
    assert sum("# Procedure" in text for text in provider.inputs) == 1
    assert all(citation["metadata"]["content_hash"] for citation in result["citations"])


async def test_graph_preflight_conflict_does_not_write_earlier_concepts() -> None:
    old = OKFDocument(path="z.md", frontmatter={"type": "Note"}, body="Already stored.")
    new = OKFDocument(path="a.md", frontmatter={"type": "Note"}, body="Must not be partially imported.")
    graph = create_knowledge_graph(create_memory_manager())
    await import_okf_bundle(OKFBundle((old,)), graph=graph, bundle_id="project")
    with pytest.raises(ValueError, match="unused namespace"):
        await import_okf_bundle(OKFBundle((new, old)), graph=graph, bundle_id="project")
    assert await graph.get_entity(new.source_id(bundle_id="project")) is None
    stored = await graph.get_entity(old.source_id(bundle_id="project"))
    assert stored is not None and stored.properties["content"] == old.render()


@pytest.mark.parametrize("mutation", ["empty_answer", "citation", "metadata", "hash", "unsupported"])
async def test_research_gate_rejects_malformed_or_unsupported_reports(mutation: str) -> None:
    import json

    from cemaf.agents.base import AgentContext
    from cemaf.core.types import NodeID
    from cemaf.interceptors.gate_eval import GateEvalInterceptor
    from cemaf.interceptors.types import DecisionKind
    from cemaf.orchestration.dag import Node
    from cemaf.orchestration.results import NodeResult
    from cemaf.retrieval.protocols import SearchResult
    from examples.app_shapes.okf_research import BUNDLE_PATH, ResearchEvidenceEval

    bundle = OKFBundle.load(BUNDLE_PATH)
    document = bundle.get("findings/calibration")
    citation = CitationTracker().track_search_result(
        SearchResult(
            document=document.to_document(bundle_id="project", revision=bundle.revision),
            score=1.0,
        )
    )
    output = {"answer": document.body.strip().splitlines()[0], "citation": citation.to_dict()}
    if mutation == "empty_answer":
        output["answer"] = " "
    elif mutation == "citation":
        output["citation"] = None
    elif mutation == "metadata":
        output["citation"]["metadata"] = None
    elif mutation == "hash":
        output["citation"]["metadata"]["content_hash"] = "forged"
    else:
        output["answer"] = "Unrelated claims about distant galaxies have no experimental basis."
    gate = GateEvalInterceptor(
        evaluators=(ResearchEvidenceEval(document, bundle_id="project", revision=bundle.revision),),
        threshold=1.0,
    )
    decision = await gate.post(
        node=Node.agent(id="research", name="Research", agent_id="researcher"),
        context=AgentContext(run_id="run", agent_id="researcher"),
        result=NodeResult(node_id=NodeID("research"), success=True, output=json.dumps(output)),
    )
    assert decision.kind == DecisionKind.REJECT
