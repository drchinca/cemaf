"""Produce real CEMAF run traces for the showcase — 7 steps, one capability each.

Every step is one ``executor.run(dag)`` through ``create_executor`` on real
primitives; the trace is whatever the EventBus carried during that run:

  1 hello     — one static agent
  2 chain     — two agents, the second reads the first's output from context
  3 parallel  — PARALLEL node fan-out; 4.0.0's default collision policy steers a
                sibling that would overwrite another's key; fan-in joiner
  4 council   — ``Node.council`` resolved by CouncilResolver + weighted aggregator
  5 auction   — ``Node.auction`` resolved by AuctionResolver + DefaultAgentSelector
                over two WRITE agents; the winner cites its sources (CitationTracker)
  6 gate      — GateEvalInterceptor (RECOVER) on the writer: short draft → hint →
                revised draft passes; OnlineEvalPipeline observes the result
  7 full flow — research → parallel → council → auction writer → gate → harvest

Agents are deterministic and offline (no LLM, no network). The only events an
agent causes itself are its own work (citations it registers); every other
event comes from the framework.

Usage:
    uv run python docs/architecture/scripts/produce_dag_trace.py            # all steps
    uv run python docs/architecture/scripts/produce_dag_trace.py --inline   # + rewrite HTML
    uv run python docs/architecture/scripts/produce_dag_trace.py --step 4
    uv run python docs/architecture/scripts/produce_dag_trace.py --check    # CI drift gate
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.agents.selection import Capability, DefaultAgentSelector
from cemaf.blueprint import BlueprintLibrary, InMemoryWritableBlueprintSource, create_blueprint_harvester
from cemaf.bootstrap import create_executor
from cemaf.citation.tracker import CitationTracker
from cemaf.context.patch import SecurityLevel
from cemaf.core.types import AgentID, NodeID
from cemaf.council.aggregator import DefaultVoteAggregator
from cemaf.council.types import AggregationMethod, CouncilConfig, Opinion
from cemaf.evals.evaluators import LengthEvaluator
from cemaf.evals.online import EvalMode, NodeEvalBinding, OnlineEvalPipeline
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event
from cemaf.interceptors import GateEvalInterceptor, GateFailureMode, create_interceptor_pipeline
from cemaf.interceptors.types import RECOVERY_HINTS_KEY
from cemaf.orchestration.dag import DAG, Condition, ConditionOperator, Edge, EdgeCondition, Node
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices
from cemaf.retrieval.memory_store import CharacterHashEmbeddingProvider, InMemoryVectorStore
from cemaf.retrieval.protocols import Document, VectorStore

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
TRACE_DIR: Final = REPO_ROOT / "docs" / "architecture" / "traces"
SHOWCASE_HTML: Final = REPO_ROOT / "docs" / "architecture" / "cemaf-graph.html"
TRACE_SCHEMA_VERSION: Final = 1
TRACE_DATA_OPEN: Final = "/*TRACE-DATA*/const TRACE_DATA = "
TRACE_DATA_CLOSE: Final = ";/*END-TRACE-DATA*/"
TRACE_DATA_RE: Final = re.compile(
    re.escape(TRACE_DATA_OPEN) + r"(.+?)" + re.escape(TRACE_DATA_CLOSE), re.DOTALL
)

CLEARANCE: Final = SecurityLevel.INTERNAL
TOPIC: Final = "TLS 1.3 handshake"
GATE_MIN_CHARS: Final = 160
SHIP: Final = "ship"
HOLD: Final = "hold"
SUFFICIENT: Final = "sufficient"
INSUFFICIENT: Final = "insufficient"
WRITE_CAPABILITY: Final = Capability.WRITE

SOURCES: Final = (
    Document(
        id="rfc-8446#section-2",
        content="TLS 1.3 handshake completes in one round trip (1-RTT) for a new connection.",
        metadata={"title": "RFC 8446 — TLS 1.3", "namespace": "standards"},
    ),
    Document(
        id="rfc-8446#section-2.3",
        content="TLS 1.3 handshake resumption supports 0-RTT early data with replay caveats.",
        metadata={"title": "RFC 8446 — 0-RTT", "namespace": "standards"},
    ),
    Document(
        id="caniuse-tls13",
        content="TLS 1.3 handshake is supported by every major browser since 2018.",
        metadata={"title": "Browser support for TLS 1.3", "namespace": "web"},
    ),
)


# ---------- trace recording ----------


@dataclass
class RunTracer:
    """Record every EventBus event with a run-relative timestamp."""

    started_ns: int = field(default_factory=time.monotonic_ns)
    events: list[dict[str, Any]] = field(default_factory=list)

    def attach(self, *, bus: InMemoryEventBus) -> None:
        """Subscribe to every event on the bus."""
        bus.subscribe_all(self._on_event)

    def _on_event(self, event: Event) -> None:
        rel_ms = (time.monotonic_ns() - self.started_ns) // 1_000_000
        # Payloads are framework-shaped JSON plus pydantic outputs; default=str keeps them readable.
        payload = json.loads(json.dumps(event.payload, default=str))
        self.events.append(
            {
                "t_ms": int(rel_ms),
                "kind": str(event.type),
                "source": event.source or "",
                "corr": event.correlation_id or "",
                "attrs": payload,
            }
        )


@dataclass(frozen=True, slots=True)
class StepRun:
    """The trace of one step plus anything the run produced off the bus."""

    step: int
    label: str
    dag_name: str
    status: str
    events: tuple[dict[str, Any], ...]
    extras: dict[str, Any] = field(default_factory=dict)

    def to_trace(self) -> dict[str, Any]:
        """The JSON shape the showcase reads."""
        return {
            "schema_version": TRACE_SCHEMA_VERSION,
            "step": self.step,
            "label": self.label,
            "dag_name": self.dag_name,
            "status": self.status,
            "total_ms": self.events[-1]["t_ms"] if self.events else 0,
            "events": list(self.events),
            **self.extras,
        }


# ---------- goals ----------


class TextGoal(BaseModel):
    text: str = ""


class ListGoal(BaseModel):
    items: list[str] = []


class TopicGoal(BaseModel):
    topic: str = TOPIC


class ReviewGoal(BaseModel):
    objective: str = "Is the evidence sufficient?"


class WriteGoal(BaseModel):
    facts: str = ""
    objective: str = "Write a short brief."


# ---------- agents ----------


class DemoAgent[GoalT: BaseModel](Agent[GoalT, str]):
    """Shared identity surface for the demo agents."""

    def __init__(self, *, agent_id: str, description: str) -> None:
        self._id = AgentID(agent_id)
        self._description = description

    @property
    def id(self) -> AgentID:
        return self._id

    @property
    def description(self) -> str:
        return self._description

    @property
    def skills(self) -> tuple[()]:
        return ()


class Greeter(DemoAgent[TextGoal]):
    """Says hello."""

    def __init__(self) -> None:
        super().__init__(agent_id="Greeter", description="Single static agent.")

    async def run(self, goal: TextGoal, context: AgentContext) -> AgentResult[str]:
        await asyncio.sleep(0.02)
        return AgentResult.ok(output=f"Hello, {goal.text}!", state=AgentState())


class Shouter(DemoAgent[TextGoal]):
    """Uppercases the previous node's output."""

    def __init__(self) -> None:
        super().__init__(agent_id="Shouter", description="Uppercases its input.")

    async def run(self, goal: TextGoal, context: AgentContext) -> AgentResult[str]:
        await asyncio.sleep(0.02)
        return AgentResult.ok(output=goal.text.upper(), state=AgentState())


class Fetcher(DemoAgent[TopicGoal]):
    """Pulls one source from the vector store; latency differs per fetcher."""

    def __init__(self, *, agent_id: str, store: VectorStore, rank: int, delay_s: float) -> None:
        super().__init__(agent_id=agent_id, description="Parallel branch: fetch one source.")
        self._store = store
        self._rank = rank
        self._delay_s = delay_s

    async def run(self, goal: TopicGoal, context: AgentContext) -> AgentResult[str]:
        await asyncio.sleep(self._delay_s)
        hits = await self._store.search_by_text(query_text=goal.topic, k=len(SOURCES))
        return AgentResult.ok(output=hits[self._rank].document.content, state=AgentState())


class Joiner(DemoAgent[ListGoal]):
    """Fan-in: merges the parallel branches."""

    def __init__(self) -> None:
        super().__init__(agent_id="Joiner", description="Merges parallel branch outputs.")

    async def run(self, goal: ListGoal, context: AgentContext) -> AgentResult[str]:
        await asyncio.sleep(0.01)
        return AgentResult.ok(output=" | ".join(goal.items), state=AgentState())


class Researcher(DemoAgent[TopicGoal]):
    """Retrieves sources and registers each one with the CitationTracker."""

    def __init__(self, *, store: VectorStore, citations: CitationTracker) -> None:
        super().__init__(agent_id="Researcher", description="Retrieves and cites sources.")
        self._store = store
        self._citations = citations

    async def run(self, goal: TopicGoal, context: AgentContext) -> AgentResult[str]:
        hits = await self._store.search_by_text(query_text=goal.topic, k=len(SOURCES))
        tracked = self._citations.track_search_results(hits)
        self._citations.create_cited_fact(
            fact=hits[0].document.content, citations=tracked, confidence=hits[0].score
        )
        return AgentResult.ok(
            output=" ".join(hit.document.content for hit in hits),
            state=AgentState(),
            metadata={"reasoning": f"retrieved {len(hits)} sources for '{goal.topic}'"},
        )


class Reviewer(DemoAgent[ReviewGoal]):
    """Council member with a fixed vote and confidence (the weighted aggregator's weight)."""

    def __init__(self, *, agent_id: str, vote: str, confidence: float, rationale: str) -> None:
        super().__init__(agent_id=agent_id, description="Votes on whether to proceed.")
        self._vote = vote
        self._confidence = confidence
        self._rationale = rationale

    async def run(self, goal: ReviewGoal, context: AgentContext) -> AgentResult[str]:
        return AgentResult.ok(output=self._vote, state=AgentState())

    async def deliberate(self, *, question: object, goal: object, context: AgentContext) -> Opinion:
        await asyncio.sleep(0.01)
        return Opinion(
            member_id=self.id, choice=self._vote, confidence=self._confidence, rationale=self._rationale
        )


class Writer(DemoAgent[WriteGoal]):
    """WRITE-capable agent; drafts short, revises to full length when a gate hint arrives."""

    def __init__(self, *, agent_id: str, load: float, delay_s: float) -> None:
        super().__init__(agent_id=agent_id, description="Writes the brief.")
        self._load = load
        self._delay_s = delay_s

    @property
    def capabilities(self) -> frozenset[Capability]:
        return frozenset({WRITE_CAPABILITY})

    @property
    def current_load(self) -> float:
        return self._load

    async def run(self, goal: WriteGoal, context: AgentContext) -> AgentResult[str]:
        await asyncio.sleep(self._delay_s)
        hints = context.global_memory.get(RECOVERY_HINTS_KEY, [])
        revising = isinstance(hints, list) and bool(hints)
        draft = "TLS 1.3 cuts the handshake to 1-RTT."
        if revising:
            draft += (
                " New connections finish the handshake in one round trip, resumed sessions can send"
                " 0-RTT early data (with replay caveats), and every major browser has shipped it since 2018."
            )
        return AgentResult.ok(
            output=draft,
            state=AgentState(),
            metadata={"cost_estimate_usd": 0.02, "tokens_total": len(draft.split()), "overall_score": 0.95},
        )


# ---------- shared wiring ----------


async def _seeded_store() -> InMemoryVectorStore:
    """Offline vector store seeded with the demo sources."""
    store = InMemoryVectorStore(embedding_provider=CharacterHashEmbeddingProvider(dimension=64))
    for doc in SOURCES:
        await store.add(doc)
    return store


def _register(*, registry: AgentRegistry, agent: Agent[Any, Any], goal_type: type[BaseModel]) -> None:
    registry.register_agent(agent_instance=agent, goal_type=goal_type)


def _register_writers(*, registry: AgentRegistry) -> None:
    """Two WRITE candidates for the auction: a busy one and an idle one."""
    for agent_id, load, delay_s in (("WriterBusy", 0.64, 0.05), ("WriterIdle", 0.05, 0.03)):
        registry.register_agent(
            agent_instance=Writer(agent_id=agent_id, load=load, delay_s=delay_s),
            goal_type=WriteGoal,
            capabilities=frozenset({WRITE_CAPABILITY}),
        )


def _register_council(*, registry: AgentRegistry, votes: tuple[str, str, str]) -> tuple[str, ...]:
    members = (
        ("ReviewerA", votes[0], 0.82, "Primary sources agree."),
        ("ReviewerB", votes[1], 0.71, "Browser support is documented."),
        ("Skeptic", votes[2], 0.58, "0-RTT replay risk is under-explained."),
    )
    for agent_id, vote, confidence, rationale in members:
        registry.register_instance(
            item=Reviewer(agent_id=agent_id, vote=vote, confidence=confidence, rationale=rationale)
        )
    return tuple(member[0] for member in members)


def _weighted_aggregator() -> DefaultVoteAggregator:
    return DefaultVoteAggregator(config=CouncilConfig(method=AggregationMethod.WEIGHTED))


def _recovering_gate(*, node_pattern: str) -> GateEvalInterceptor:
    return GateEvalInterceptor(
        evaluators=(LengthEvaluator(min_length=GATE_MIN_CHARS),),
        node_pattern=node_pattern,
        threshold=0.5,
        on_failure=GateFailureMode.RECOVER,
    )


def _add_parallel_fetch(*, dag: DAG, store: VectorStore, registry: AgentRegistry) -> DAG:
    """Add a PARALLEL node over three fetchers; the third would overwrite the first's key.

    Edges run from the PARALLEL node to each child so topological order dispatches the
    group before any child could run on its own.
    """
    fetchers = (
        ("fetch_spec", "FetcherSpec", 0, 0.06, "spec_source"),
        ("fetch_web", "FetcherWeb", 2, 0.10, "web_source"),
        ("fetch_spec_again", "FetcherSpecMirror", 1, 0.04, "spec_source"),
    )
    nodes: list[Node] = [
        Node.parallel(
            id="fan",
            name="Fan out",
            parallel_nodes=[node_id for node_id, *_ in fetchers],
            output_key="fan_out",
        )
    ]
    for node_id, agent_id, rank, delay_s, output_key in fetchers:
        _register(
            registry=registry,
            agent=Fetcher(agent_id=agent_id, store=store, rank=rank, delay_s=delay_s),
            goal_type=TopicGoal,
        )
        nodes.append(
            Node.agent(
                id=node_id,
                name=agent_id,
                agent_id=agent_id,
                input_mapping={"topic": TOPIC},
                output_key=output_key,
            )
        )
    for node in nodes:
        dag = dag.add_node(node=node)
    for node_id, *_ in fetchers:
        dag = dag.add_edge(edge=Edge(source=NodeID("fan"), target=NodeID(node_id)))
    return dag


async def _run(
    *,
    step: int,
    label: str,
    dag: DAG,
    registry: AgentRegistry,
    bus: InMemoryEventBus,
    tracer: RunTracer,
    services: RuntimeServices,
    online: OnlineEvalPipeline | None = None,
) -> StepRun:
    executor = create_executor(
        agent_registry=registry,
        clearance=CLEARANCE,
        config=ExecutorConfig(enable_events=True),
        services=services,
    )
    tracer.started_ns = time.monotonic_ns()
    result = await executor.run(dag=dag)
    if online is not None:
        await online.flush()
    # CitationTracker publishes from sync code via loop.create_task; let those land.
    await asyncio.sleep(0)
    return StepRun(
        step=step,
        label=label,
        dag_name=dag.name,
        status=result.status.value,
        events=tuple(tracer.events),
    )


def _bus_and_tracer() -> tuple[InMemoryEventBus, RunTracer]:
    bus = InMemoryEventBus()
    tracer = RunTracer()
    tracer.attach(bus=bus)
    return bus, tracer


# ---------- steps ----------


async def step1_hello() -> StepRun:
    """One static agent."""
    bus, tracer = _bus_and_tracer()
    registry = AgentRegistry()
    _register(registry=registry, agent=Greeter(), goal_type=TextGoal)
    dag = DAG(name="hello").add_node(
        node=Node.agent(
            id="greet",
            name="Greeter",
            agent_id="Greeter",
            input_mapping={"text": "world"},
            output_key="greeting",
        )
    )
    return await _run(
        step=1,
        label=STEP_LABELS[1],
        dag=dag,
        registry=registry,
        bus=bus,
        tracer=tracer,
        services=RuntimeServices(event_bus=bus),
    )


async def step2_chain() -> StepRun:
    """Two agents; the second reads the first's output through context."""
    bus, tracer = _bus_and_tracer()
    registry = AgentRegistry()
    _register(registry=registry, agent=Greeter(), goal_type=TextGoal)
    _register(registry=registry, agent=Shouter(), goal_type=TextGoal)
    dag = (
        DAG(name="chain")
        .add_node(
            node=Node.agent(
                id="greet",
                name="Greeter",
                agent_id="Greeter",
                input_mapping={"text": "world"},
                output_key="greeting",
            )
        )
        .add_node(
            node=Node.agent(
                id="shout",
                name="Shouter",
                agent_id="Shouter",
                input_mapping={"text": "$$greeting$$"},
                output_key="loud",
            )
        )
        .add_edge(edge=Edge(source=NodeID("greet"), target=NodeID("shout")))
    )
    return await _run(
        step=2,
        label=STEP_LABELS[2],
        dag=dag,
        registry=registry,
        bus=bus,
        tracer=tracer,
        services=RuntimeServices(event_bus=bus),
    )


async def step3_parallel() -> StepRun:
    """PARALLEL fan-out with default collision coordination, then a fan-in joiner."""
    bus, tracer = _bus_and_tracer()
    store = await _seeded_store()
    registry = AgentRegistry()
    _register(registry=registry, agent=Joiner(), goal_type=ListGoal)
    dag = _add_parallel_fetch(dag=DAG(name="parallel"), store=store, registry=registry)
    dag = dag.add_node(
        node=Node.agent(
            id="join",
            name="Joiner",
            agent_id="Joiner",
            input_mapping={"items": ["$$spec_source$$", "$$web_source$$"]},
            output_key="merged",
        )
    ).add_edge(edge=Edge(source=NodeID("fan"), target=NodeID("join")))
    # RuntimeServices() carries the 4.0.0 default collision_policy; nothing to opt into.
    return await _run(
        step=3,
        label=STEP_LABELS[3],
        dag=dag,
        registry=registry,
        bus=bus,
        tracer=tracer,
        services=RuntimeServices(event_bus=bus),
    )


async def step4_council() -> StepRun:
    """Node.council resolved by CouncilResolver with a weighted aggregator."""
    bus, tracer = _bus_and_tracer()
    store = await _seeded_store()
    citations = CitationTracker(event_bus=bus)
    registry = AgentRegistry()
    _register(registry=registry, agent=Researcher(store=store, citations=citations), goal_type=TopicGoal)
    members = _register_council(registry=registry, votes=(SUFFICIENT, SUFFICIENT, INSUFFICIENT))
    dag = (
        DAG(name="council")
        .add_node(node=Node.agent(id="research", name="Research", agent_id="Researcher", output_key="facts"))
        .add_node(
            node=Node.council(
                id="vote",
                name="Evidence review",
                members=members,
                options=(SUFFICIENT, INSUFFICIENT),
                output_key="verdict",
            )
        )
        .add_edge(edge=Edge(source=NodeID("research"), target=NodeID("vote")))
    )
    return await _run(
        step=4,
        label=STEP_LABELS[4],
        dag=dag,
        registry=registry,
        bus=bus,
        tracer=tracer,
        services=RuntimeServices(event_bus=bus, council_aggregator=_weighted_aggregator()),
    )


async def step5_auction() -> StepRun:
    """Node.auction resolved by AuctionResolver; the low-load WRITE agent wins."""
    bus, tracer = _bus_and_tracer()
    store = await _seeded_store()
    citations = CitationTracker(event_bus=bus)
    registry = AgentRegistry()
    _register(registry=registry, agent=Researcher(store=store, citations=citations), goal_type=TopicGoal)
    _register_writers(registry=registry)
    dag = (
        DAG(name="auction")
        .add_node(node=Node.agent(id="research", name="Research", agent_id="Researcher", output_key="facts"))
        .add_node(
            node=Node.auction(
                id="write",
                name="Write",
                capability=WRITE_CAPABILITY.value,
                input_mapping={"facts": "$$facts$$"},
                output_key="draft",
            )
        )
        .add_edge(edge=Edge(source=NodeID("research"), target=NodeID("write")))
    )
    return await _run(
        step=5,
        label=STEP_LABELS[5],
        dag=dag,
        registry=registry,
        bus=bus,
        tracer=tracer,
        services=RuntimeServices(event_bus=bus, agent_selector=DefaultAgentSelector()),
    )


async def step6_gate() -> StepRun:
    """GateEvalInterceptor RECOVERs a short draft; the revised draft passes; online eval observes."""
    bus, tracer = _bus_and_tracer()
    registry = AgentRegistry()
    registry.register_agent(
        agent_instance=Writer(agent_id="Writer", load=0.1, delay_s=0.03),
        goal_type=WriteGoal,
    )
    online = OnlineEvalPipeline(
        bindings=(
            NodeEvalBinding(
                node_pattern="write",
                evaluators=(LengthEvaluator(min_length=GATE_MIN_CHARS),),
                mode=EvalMode.OBSERVE,
            ),
        ),
        event_bus=bus,
    )
    dag = DAG(name="gate").add_node(
        node=Node.agent(id="write", name="Write", agent_id="Writer", output_key="draft")
    )
    services = RuntimeServices(
        event_bus=bus,
        online_eval_pipeline=online,
        interceptor_pipeline=create_interceptor_pipeline(
            interceptors=(_recovering_gate(node_pattern="write"),)
        ),
    )
    return await _run(
        step=6,
        label=STEP_LABELS[6],
        dag=dag,
        registry=registry,
        bus=bus,
        tracer=tracer,
        services=services,
        online=online,
    )


async def step7_full() -> StepRun:
    """Research → parallel → council → auction writer → gate → harvest in one run."""
    bus, tracer = _bus_and_tracer()
    store = await _seeded_store()
    citations = CitationTracker(event_bus=bus)
    registry = AgentRegistry()
    _register(registry=registry, agent=Researcher(store=store, citations=citations), goal_type=TopicGoal)
    members = _register_council(registry=registry, votes=(SHIP, SHIP, HOLD))
    _register_writers(registry=registry)

    online = OnlineEvalPipeline(
        bindings=(
            NodeEvalBinding(
                node_pattern="write",
                evaluators=(LengthEvaluator(min_length=GATE_MIN_CHARS),),
                mode=EvalMode.OBSERVE,
            ),
        ),
        event_bus=bus,
    )
    harvest_source = InMemoryWritableBlueprintSource()
    create_blueprint_harvester(
        writable_source=harvest_source,
        event_bus=bus,
        library=BlueprintLibrary(),
        threshold=0.8,
    )

    dag = DAG(name="full_flow").add_node(
        node=Node.agent(id="research", name="Research", agent_id="Researcher", output_key="facts")
    )
    dag = _add_parallel_fetch(dag=dag, store=store, registry=registry)
    dag = (
        dag.add_node(
            node=Node.council(
                id="plan",
                name="Ship or hold",
                members=members,
                options=(SHIP, HOLD),
                output_key="plan_verdict",
            )
        )
        .add_node(
            node=Node.auction(
                id="write",
                name="Write",
                capability=WRITE_CAPABILITY.value,
                input_mapping={"facts": "$$facts$$"},
                output_key="draft",
            )
        )
        .add_edge(edge=Edge(source=NodeID("research"), target=NodeID("fan")))
        .add_edge(edge=Edge(source=NodeID("fan"), target=NodeID("plan")))
        .add_edge(
            edge=Edge(
                source=NodeID("plan"),
                target=NodeID("write"),
                condition=EdgeCondition.JSON_RULE,
                condition_rule=Condition(field="plan_verdict", operator=ConditionOperator.EQUALS, value=SHIP),
            )
        )
    )
    services = RuntimeServices(
        event_bus=bus,
        agent_selector=DefaultAgentSelector(),
        council_aggregator=_weighted_aggregator(),
        online_eval_pipeline=online,
        interceptor_pipeline=create_interceptor_pipeline(
            interceptors=(_recovering_gate(node_pattern="write"),)
        ),
    )
    run = await _run(
        step=7,
        label=STEP_LABELS[7],
        dag=dag,
        registry=registry,
        bus=bus,
        tracer=tracer,
        services=services,
        online=online,
    )
    # The harvester reports through its writable source, not the bus; record what it kept.
    harvested = [blueprint.id for blueprint in harvest_source.load()]
    return StepRun(
        step=run.step,
        label=run.label,
        dag_name=run.dag_name,
        status=run.status,
        events=run.events,
        extras={"blueprints_harvested": harvested},
    )


STEP_LABELS: Final[dict[int, str]] = {
    1: "hello — single agent",
    2: "chain — 2 agents",
    3: "parallel — fan-out + collision steer + fan-in",
    4: "council — 3-member weighted vote",
    5: "auction + writer — competitive selection",
    6: "quality gate — eval interceptor + recover",
    7: "full flow — research→parallel→council→auction→gate→harvest",
}

STEPS: Final[dict[int, Callable[[], Awaitable[StepRun]]]] = {
    1: step1_hello,
    2: step2_chain,
    3: step3_parallel,
    4: step4_council,
    5: step5_auction,
    6: step6_gate,
    7: step7_full,
}


# ---------- output ----------


def _index() -> dict[str, Any]:
    return {
        "schema_version": TRACE_SCHEMA_VERSION,
        "steps": [
            {"step": s, "label": STEP_LABELS[s], "path": f"traces/step-{s}.json"} for s in sorted(STEPS)
        ],
    }


async def run_steps(*, steps: list[int], out_dir: Path) -> dict[int, dict[str, Any]]:
    """Run the given steps and write step-N.json + index.json into out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    traces: dict[int, dict[str, Any]] = {}
    for step in steps:
        run = await STEPS[step]()
        trace = run.to_trace()
        (out_dir / f"step-{step}.json").write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")
        kinds = sorted({e["kind"] for e in trace["events"]})
        print(
            f"step {step}  {run.label:<58} status={run.status:<9} events={len(trace['events']):>3}  {kinds}"
        )
        traces[step] = trace
    (out_dir / "index.json").write_text(json.dumps(_index(), indent=2) + "\n", encoding="utf-8")
    return traces


def _read_inlined(*, html: str) -> dict[str, Any]:
    match = TRACE_DATA_RE.search(html)
    if match is None:
        raise ValueError(f"no {TRACE_DATA_OPEN.strip()} block in {SHOWCASE_HTML.name}")
    data: dict[str, Any] = json.loads(match.group(1))
    return data


def inline_traces(*, trace_dir: Path) -> None:
    """Rewrite the TRACE_DATA block in cemaf-graph.html from the on-disk traces."""
    traces = {
        str(s): json.loads((trace_dir / f"step-{s}.json").read_text(encoding="utf-8")) for s in sorted(STEPS)
    }
    payload = json.dumps({"index": _index(), "traces": traces}, separators=(",", ":"))
    # Keep a literal "</script>" in any payload from closing the inline script.
    payload = payload.replace("</", "<\\/")
    html = SHOWCASE_HTML.read_text(encoding="utf-8")
    if TRACE_DATA_RE.search(html) is None:
        raise ValueError(f"no {TRACE_DATA_OPEN.strip()} block in {SHOWCASE_HTML.name}")
    replacement = TRACE_DATA_OPEN + payload + TRACE_DATA_CLOSE
    html = TRACE_DATA_RE.sub(lambda _match: replacement, html, count=1)
    SHOWCASE_HTML.write_text(html, encoding="utf-8")
    print(f"\n  inlined {len(traces)} traces into {SHOWCASE_HTML.relative_to(REPO_ROOT)}")


def _kinds(*, trace: dict[str, Any]) -> set[str]:
    return {e["kind"] for e in trace["events"]}


async def check() -> int:
    """Fail on drift: inlined vs on-disk, and inlined vs a fresh run of every step."""
    try:
        inlined = _read_inlined(html=SHOWCASE_HTML.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}")
        return 1

    drift: list[str] = []
    if inlined.get("index") != _index():
        drift.append("inlined index differs from the producer's step labels/paths")

    with tempfile.TemporaryDirectory(prefix="cemaf-traces-") as tmp:
        try:
            fresh = await run_steps(steps=sorted(STEPS), out_dir=Path(tmp))
        except Exception as exc:  # the producer itself is broken — that is the drift
            print(f"FAIL: producer could not run: {type(exc).__name__}: {exc}")
            return 1

    for step in sorted(STEPS):
        inl = inlined.get("traces", {}).get(str(step))
        if inl is None:
            drift.append(f"step {step} missing in inlined TRACE_DATA")
            continue
        disk_path = TRACE_DIR / f"step-{step}.json"
        if not disk_path.exists():
            drift.append(f"{disk_path.relative_to(REPO_ROOT)} missing")
        else:
            disk = json.loads(disk_path.read_text(encoding="utf-8"))
            if len(inl["events"]) != len(disk["events"]) or _kinds(trace=inl) != _kinds(trace=disk):
                drift.append(f"step {step}: inlined trace differs from {disk_path.name}")
        if fresh[step]["status"] != "completed":
            drift.append(f"step {step}: fresh run ended {fresh[step]['status']}")
        if _kinds(trace=inl) != _kinds(trace=fresh[step]):
            drift.append(
                f"step {step}: event kinds differ from a fresh run "
                f"(only inlined: {sorted(_kinds(trace=inl) - _kinds(trace=fresh[step]))}, "
                f"only fresh: {sorted(_kinds(trace=fresh[step]) - _kinds(trace=inl))})"
            )

    if drift:
        print("TRACE_DATA drift — run `make demo` (produce_dag_trace.py --inline) and commit:")
        for item in drift:
            print(f"  ✗ {item}")
        return 1
    print(f"TRACE_DATA in {SHOWCASE_HTML.name} matches disk and a fresh run of all {len(STEPS)} steps")
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description="Produce the showcase's real CEMAF run traces.")
    parser.add_argument("--step", type=int, choices=sorted(STEPS), help="Run a single step (default: all)")
    parser.add_argument("--inline", action="store_true", help="Also rewrite TRACE_DATA in cemaf-graph.html")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run every step into a temp dir and fail if the inlined TRACE_DATA drifted. Writes nothing.",
    )
    args = parser.parse_args()

    if args.check:
        return await check()
    steps = [args.step] if args.step else sorted(STEPS)
    await run_steps(steps=steps, out_dir=TRACE_DIR)
    if args.inline:
        inline_traces(trace_dir=TRACE_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
