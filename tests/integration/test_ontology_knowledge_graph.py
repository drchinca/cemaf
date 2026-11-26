"""SPEC-27 §4 scenarios through a real MemoryBackedKnowledgeGraph and a real InMemoryEventBus."""

from __future__ import annotations

from dataclasses import replace

import pytest

from cemaf.agents.base import AgentContext
from cemaf.agents.registry import AgentRegistry
from cemaf.context.patch import SecurityLevel
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType
from cemaf.knowledge.graph import MemoryBackedKnowledgeGraph
from cemaf.knowledge.models import KGEntity, KGRelation
from cemaf.knowledge.okf import OKFBundle, OKFDocument
from cemaf.knowledge.okf_graph import import_okf_bundle
from cemaf.knowledge.ontology import Ontology, ViolationKind
from cemaf.knowledge.ontology_graph import OntologyKnowledgeGraph
from cemaf.knowledge.protocols import KnowledgeGraph
from cemaf.knowledge.self_ontology import CEMAF_SELF_ONTOLOGY
from cemaf.memory.factories import create_memory_manager
from cemaf.meta.bootstrap import MetaServices, create_meta_executor
from cemaf.meta.goals import SolutionGoal
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices
from cemaf.tools.registry import ToolRegistry
from tests.unit.knowledge.test_ontology import service_catalog


class Harness:
    """A checked graph over a real memory-backed graph, with every published event captured."""

    def __init__(self, *, ontology: Ontology | None = None, recent_violation_limit: int = 1_000) -> None:
        self.memory = create_memory_manager()
        self.raw = MemoryBackedKnowledgeGraph(
            memory_manager=self.memory, clearance=SecurityLevel.CONFIDENTIAL
        )
        self.bus = InMemoryEventBus()
        self.events: list[Event] = []
        self.bus.subscribe(event_type=EventType.ONTOLOGY_VIOLATION, handler=self._capture)
        self.graph = OntologyKnowledgeGraph(
            graph=self.raw,
            ontology=ontology or service_catalog(),
            event_bus=self.bus,
            recent_violation_limit=recent_violation_limit,
        )

    async def _capture(self, event: Event) -> None:
        self.events.append(event)

    def kinds(self) -> list[ViolationKind]:
        return [violation.kind for violation in self.graph.recent_violations()]


def _service(*, entity_id: str, tier: str | None = "critical", **extra: object) -> KGEntity:
    properties: dict[str, object] = {} if tier is None else {"tier": tier}
    properties.update(extra)
    return KGEntity(id=entity_id, type="Service", name=entity_id, properties=properties)


def _engineer(*, entity_id: str) -> KGEntity:
    return KGEntity(
        id=entity_id, type="Engineer", name=entity_id, properties={"email": f"{entity_id}@example.com"}
    )


def test_the_wrapper_is_a_knowledge_graph() -> None:
    assert isinstance(Harness().graph, KnowledgeGraph)


@pytest.mark.asyncio
async def test_a_valid_write_is_quiet() -> None:
    h = Harness()

    await h.graph.add_entity(_service(entity_id="svc-1"))

    assert await h.raw.get_entity(entity_id="svc-1") is not None
    assert h.graph.recent_violations() == ()
    assert h.events == []


@pytest.mark.asyncio
async def test_a_missing_required_property_is_recorded_published_and_still_stored() -> None:
    h = Harness()

    await h.graph.add_entity(_service(entity_id="svc-1", tier=None))

    assert await h.raw.get_entity(entity_id="svc-1") is not None
    assert h.kinds() == [ViolationKind.MISSING_PROPERTY]
    assert [event.payload for event in h.events] == [
        {
            "ontology": "service-catalog",
            "version": 1,
            "kind": "missing_property",
            "subject_id": "svc-1",
            "message": "Service requires property 'tier'",
        }
    ]


@pytest.mark.asyncio
async def test_a_value_outside_the_allowed_list_is_recorded() -> None:
    h = Harness()

    await h.graph.add_entity(_service(entity_id="svc-1", tier="legendary"))

    assert h.kinds() == [ViolationKind.VALUE_NOT_ALLOWED]


@pytest.mark.asyncio
async def test_a_relation_between_the_wrong_classes_is_recorded_and_written() -> None:
    h = Harness()
    await h.graph.add_entity(_service(entity_id="svc-1"))
    await h.graph.add_entity(KGEntity(id="team-1", type="Team", name="Payments"))

    await h.graph.add_relation(KGRelation(source_id="svc-1", target_id="team-1", type="owns"))

    assert h.kinds() == [ViolationKind.WRONG_SOURCE_CLASS, ViolationKind.WRONG_TARGET_CLASS]
    assert len(await h.raw.relations_from(entity_id="svc-1", relation_type="owns")) == 1


@pytest.mark.asyncio
async def test_cardinality_counts_the_sources_existing_relations() -> None:
    h = Harness()
    await h.graph.add_entity(_engineer(entity_id="eng-1"))
    for n in range(4):
        await h.graph.add_entity(_service(entity_id=f"svc-{n}"))
    for n in range(3):
        await h.graph.add_relation(KGRelation(source_id="eng-1", target_id=f"svc-{n}", type="on_call_for"))
    assert h.kinds() == []

    await h.graph.add_relation(KGRelation(source_id="eng-1", target_id="svc-3", type="on_call_for"))

    assert h.kinds() == [ViolationKind.TOO_MANY_RELATIONS]
    assert len(await h.raw.relations_from(entity_id="eng-1", relation_type="on_call_for")) == 4


@pytest.mark.asyncio
async def test_rewriting_an_existing_relation_is_not_a_cardinality_break() -> None:
    h = Harness()
    await h.graph.add_entity(_engineer(entity_id="eng-1"))
    for n in range(3):
        await h.graph.add_entity(_service(entity_id=f"svc-{n}"))
        await h.graph.add_relation(KGRelation(source_id="eng-1", target_id=f"svc-{n}", type="on_call_for"))

    await h.graph.add_relation(KGRelation(source_id="eng-1", target_id="svc-1", type="on_call_for"))

    assert h.kinds() == []


@pytest.mark.asyncio
async def test_an_endpoint_above_the_readers_clearance_is_missing_not_revealed() -> None:
    h = Harness()
    await h.raw.add_entity(KGEntity(id="team-1", type="Team", name="Payments"))
    await h.raw.add_entity(
        replace(_service(entity_id="svc-secret"), security_level=SecurityLevel.CONFIDENTIAL),
    )
    reader = MemoryBackedKnowledgeGraph(memory_manager=h.memory, clearance=SecurityLevel.INTERNAL)
    checked = OntologyKnowledgeGraph(graph=reader, ontology=service_catalog())

    await checked.add_relation(KGRelation(source_id="team-1", target_id="svc-secret", type="owns"))

    assert [(v.kind, v.message) for v in checked.recent_violations()] == [
        (ViolationKind.MISSING_ENDPOINT, "target svc-secret not found or not visible")
    ]


@pytest.mark.asyncio
async def test_a_closed_class_reports_an_undeclared_property() -> None:
    catalog = service_catalog()
    closed = tuple(replace(cls, closed=True) if cls.name == "Service" else cls for cls in catalog.classes)
    h = Harness(ontology=replace(catalog, classes=closed))

    await h.graph.add_entity(_service(entity_id="svc-1", colour="teal"))

    assert h.kinds() == [ViolationKind.UNKNOWN_PROPERTY]


@pytest.mark.asyncio
async def test_querying_a_class_includes_its_subclasses() -> None:
    h = Harness()
    await h.graph.add_entity(
        KGEntity(id="p-1", type="Person", name="Grace", properties={"email": "g@example.com"})
    )
    await h.graph.add_entity(_engineer(entity_id="eng-1"))
    await h.graph.add_entity(_service(entity_id="svc-1"))

    everyone = await h.graph.entities_of_class(class_name="Person")
    only_people = await h.graph.entities_of_class(class_name="Person", include_subclasses=False)

    assert [e.id for e in everyone] == ["eng-1", "p-1"]
    assert [e.id for e in only_people] == ["p-1"]


@pytest.mark.asyncio
async def test_walking_a_typed_relation_returns_its_targets() -> None:
    h = Harness()
    await h.graph.add_entity(KGEntity(id="team-1", type="Team", name="Payments"))
    await h.graph.add_entity(_engineer(entity_id="eng-1"))
    for n in range(2):
        await h.graph.add_entity(_service(entity_id=f"svc-{n}"))
        await h.graph.add_relation(KGRelation(source_id="team-1", target_id=f"svc-{n}", type="owns"))
    await h.graph.add_relation(KGRelation(source_id="eng-1", target_id="team-1", type="member_of"))

    owned = await h.graph.related(entity_id="team-1", relation="owns")

    assert sorted(e.id for e in owned) == ["svc-0", "svc-1"]
    assert await h.graph.related(entity_id="svc-0", relation="owns") == ()


@pytest.mark.asyncio
async def test_the_recent_window_keeps_the_newest_while_events_carry_every_violation() -> None:
    h = Harness(recent_violation_limit=2)

    for n in range(3):
        await h.graph.add_entity(_service(entity_id=f"svc-{n}", tier=None))

    assert [v.subject_id for v in h.graph.recent_violations()] == ["svc-1", "svc-2"]
    assert len(h.events) == 3


@pytest.mark.asyncio
async def test_reads_pass_through_and_branching_is_not_advertised() -> None:
    h = Harness()
    await h.graph.add_entity(_service(entity_id="svc-1"))

    assert (await h.graph.get_entity(entity_id="svc-1")) == (await h.raw.get_entity(entity_id="svc-1"))
    assert [e.id for e in await h.graph.search(query="svc", entity_type="Service")] == ["svc-1"]
    assert h.graph.capabilities.branching is False
    assert await h.graph.remove_entity(entity_id="svc-1") is True
    assert await h.raw.get_entity(entity_id="svc-1") is None


def test_the_recent_window_must_hold_something() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        OntologyKnowledgeGraph(graph=Harness().raw, ontology=service_catalog(), recent_violation_limit=0)


class TestCemafSelfOntology:
    """Invariant 10: CEMAF's real writes fit CEMAF_SELF_ONTOLOGY, and a broken write is still caught."""

    @staticmethod
    def _checked_graph() -> Harness:
        return Harness(ontology=CEMAF_SELF_ONTOLOGY)

    @pytest.mark.asyncio
    async def test_solution_versioning_fits_the_self_ontology(self) -> None:
        h = self._checked_graph()
        agent_registry, tool_registry = AgentRegistry(), ToolRegistry()
        create_meta_executor(
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            services=RuntimeServices(event_bus=h.bus, memory_manager=h.memory),
            meta_services=MetaServices(knowledge_graph=h.graph),
            config=ExecutorConfig(enable_events=False),
            clearance=SecurityLevel.CONFIDENTIAL,
        )
        designer = agent_registry.get("MetaSolutionDesigner")
        assert designer is not None

        result = await designer.run(
            goal=SolutionGoal(
                use_case="Route support tickets", constraints={"max_agents": 3}, version_tag="v2"
            ),
            context=AgentContext(run_id="self-ontology", agent_id="MetaSolutionDesigner"),
        )

        assert result.success
        versions = await h.raw.entities_of_type(entity_type="dag")
        assert len(versions) == 1
        assert versions[0].properties["version"] == "v2"
        assert isinstance(versions[0].properties["node_count"], int)
        assert h.graph.recent_violations() == ()

    @pytest.mark.asyncio
    async def test_an_okf_import_fits_the_self_ontology(self) -> None:
        h = self._checked_graph()
        finding = OKFDocument(
            path="findings/latency.md",
            frontmatter={
                "type": "Finding",
                "title": "Latency",
                "sources": [{"resource": "../runbooks/load.md"}],
            },
            body="p99 doubled under load. See [runbook](/runbooks/load.md).",
        )
        runbook = OKFDocument(path="runbooks/load.md", frontmatter={"type": "Runbook"}, body="Ramp to 2x.")

        imported = await import_okf_bundle(OKFBundle((finding, runbook)), graph=h.graph, bundle_id="ops")

        assert (imported.entity_count, imported.relation_count) == (2, 2)
        assert h.graph.recent_violations() == ()

    @pytest.mark.asyncio
    async def test_a_wrongly_typed_dag_property_is_still_caught(self) -> None:
        h = self._checked_graph()

        await h.graph.add_entity(
            KGEntity(id="dag-1", type="dag", name="broken", properties={"node_count": "five"})
        )

        assert h.kinds() == [ViolationKind.WRONG_PROPERTY_TYPE]
        assert await h.raw.get_entity(entity_id="dag-1") is not None
