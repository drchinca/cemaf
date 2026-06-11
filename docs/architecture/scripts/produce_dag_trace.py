"""
Produce real CEMAF run traces for the docs viz — 7 steps, each adds one
capability so an investor sees the framework evolve from hello-world to
the full machinery.

Step 1: hello — single static agent
Step 2: chain — 2 agents in sequence (events bus produces structured trace)
Step 3: parallel — 2 agents fan-out, 1 fan-in
Step 4: council — 3-member deliberation, weighted vote
Step 5: auction + writer — competitive agent selection + a citation step
Step 6: eval gate — composite quality gate, threshold-based pass/fail
Step 7: full flow — research → council → auction(writer) → cite → gate
                    → publish → harvest, with tier hits + extraction events

Every step subscribes to the EventBus and writes a JSON trace into:
    docs/architecture/traces/step-N.json

The viz at docs/architecture/cemaf-graph.html consumes those JSONs.

Usage:
    uv run python examples/produce_dag_trace.py             # writes all steps
    uv run python examples/produce_dag_trace.py --step 4    # writes only step 4
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from cemaf import (
    Agent,
    AgentContext,
    AgentRegistry,
    AgentResult,
    AgentState,
    DAG,
    Node,
    create_executor,
)
from cemaf.core.types import AgentID
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event
from cemaf.orchestration.dag import Edge
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices


REPO_ROOT = Path(__file__).resolve().parents[3]
TRACE_DIR = REPO_ROOT / "docs" / "architecture" / "traces"


# ---------- tracer ----------


@dataclass
class RunTracer:
    """Subscribes to the EventBus and records every event with relative timestamp."""

    started_ns: int = field(default_factory=time.monotonic_ns)
    events: list[dict[str, Any]] = field(default_factory=list)

    def attach(self, bus: InMemoryEventBus) -> None:
        bus.subscribe_all(self._on_event)

    def reset(self) -> None:
        self.started_ns = time.monotonic_ns()
        self.events.clear()

    def _on_event(self, event: Event) -> None:
        rel_ms = (time.monotonic_ns() - self.started_ns) // 1_000_000
        try:
            payload = json.loads(json.dumps(event.payload, default=str))
        except (TypeError, ValueError):
            payload = {"_unserializable": str(event.payload)}
        self.events.append(
            {
                "t_ms": int(rel_ms),
                "kind": event.type,
                "source": event.source or "",
                "corr": event.correlation_id or "",
                "attrs": payload,
            }
        )

    def to_dict(self, *, step: int, label: str, dag_name: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "step": step,
            "label": label,
            "dag_name": dag_name,
            "total_ms": self.events[-1]["t_ms"] if self.events else 0,
            "events": list(self.events),
        }


# ---------- helpers ----------


async def _emit(ctx: AgentContext, kind: str, payload: dict[str, Any], source: str) -> None:
    """Publish an event from inside an agent (handles missing event_bus gracefully)."""
    bus = getattr(ctx, "event_bus", None)
    if bus is None:
        return
    await bus.publish(
        Event.create(
            type=kind, payload=payload, source=source, correlation_id=getattr(ctx, "correlation_id", None)
        )
    )


def _write(tracer: RunTracer, *, step: int, label: str, dag_name: str) -> Path:
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    path = TRACE_DIR / f"step-{step}.json"
    payload = tracer.to_dict(step=step, label=label, dag_name=dag_name)
    path.write_text(json.dumps(payload, indent=2))
    return path


# ---------- shared agent payloads ----------


class TextGoal(BaseModel):
    text: str = Field(default="")


class TextResult(BaseModel):
    text: str
    tokens_in: int = 0
    tokens_out: int = 0


class ListGoal(BaseModel):
    items: list[str] = Field(default_factory=list)


class ListResult(BaseModel):
    items: list[str] = Field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0


# ---------- Step 1: hello world (single static agent) ----------


class GreeterAgent(Agent[TextGoal, TextResult]):
    @property
    def id(self) -> AgentID:
        return AgentID("Greeter")

    @property
    def description(self) -> str:
        return "Single static agent — the simplest CEMAF run."

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: TextGoal, context: AgentContext) -> AgentResult[TextResult]:
        await asyncio.sleep(0.06)
        return AgentResult.ok(
            output=TextResult(text=f"Hello, {goal.text}!", tokens_in=12, tokens_out=8),
            state=AgentState(),
        )


# ---------- Step 2: chain (2 agents) ----------


class UpperAgent(Agent[TextGoal, TextResult]):
    @property
    def id(self) -> AgentID:
        return AgentID("Upper")

    @property
    def description(self) -> str:
        return "Uppercases its input."

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: TextGoal, context: AgentContext) -> AgentResult[TextResult]:
        await asyncio.sleep(0.05)
        return AgentResult.ok(
            output=TextResult(text=goal.text.upper(), tokens_in=18, tokens_out=18),
            state=AgentState(),
        )


# ---------- Step 3: parallel fan-out + fan-in ----------


class FetcherA(Agent[TextGoal, TextResult]):
    @property
    def id(self) -> AgentID:
        return AgentID("FetcherA")

    @property
    def description(self) -> str:
        return "Parallel branch A — 'fast source'."

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: TextGoal, context: AgentContext) -> AgentResult[TextResult]:
        await asyncio.sleep(0.10)
        await _emit(context, "memory.hit", {"tier": "L0", "hits": 1}, "FetcherA")
        return AgentResult.ok(output=TextResult(text="A:" + goal.text, tokens_in=24, tokens_out=10), state=AgentState())


class FetcherB(Agent[TextGoal, TextResult]):
    @property
    def id(self) -> AgentID:
        return AgentID("FetcherB")

    @property
    def description(self) -> str:
        return "Parallel branch B — 'slow but rich source'."

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: TextGoal, context: AgentContext) -> AgentResult[TextResult]:
        await asyncio.sleep(0.16)
        await _emit(context, "memory.hit", {"tier": "L1", "hits": 3}, "FetcherB")
        return AgentResult.ok(output=TextResult(text="B:" + goal.text, tokens_in=64, tokens_out=32), state=AgentState())


class JoinerAgent(Agent[ListGoal, TextResult]):
    @property
    def id(self) -> AgentID:
        return AgentID("Joiner")

    @property
    def description(self) -> str:
        return "Fan-in — merges parallel branch outputs."

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: ListGoal, context: AgentContext) -> AgentResult[TextResult]:
        await asyncio.sleep(0.04)
        return AgentResult.ok(output=TextResult(text=" + ".join(goal.items), tokens_in=20, tokens_out=14), state=AgentState())


# ---------- Step 4: council (3-member weighted vote) ----------


class CouncilGoal(BaseModel):
    findings: list[str]


class CouncilResult(BaseModel):
    decision: str
    weighted_score: float


class CouncilAgent(Agent[CouncilGoal, CouncilResult]):
    @property
    def id(self) -> AgentID:
        return AgentID("Council")

    @property
    def description(self) -> str:
        return "Three-member council: weighted-majority aggregator."

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: CouncilGoal, context: AgentContext) -> AgentResult[CouncilResult]:
        ballots = [("ResearcherA", "sufficient", 0.82), ("ResearcherB", "sufficient", 0.71), ("Skeptic", "insufficient", 0.58)]
        for who, vote, weight in ballots:
            await _emit(context, "council.ballot", {"agent": who, "vote": vote, "weight": weight}, "Council")
            await asyncio.sleep(0.03)
        score = round((0.82 + 0.71) - 0.58, 2)
        await _emit(context, "council.decided", {"decision": "sufficient", "weighted_score": score}, "Council")
        return AgentResult.ok(output=CouncilResult(decision="sufficient", weighted_score=score), state=AgentState())


# ---------- Step 5: auction + writer with citations ----------


class WriterGoal(BaseModel):
    findings: list[str]


class CitationOut(BaseModel):
    claim: str
    src: str
    supported: bool
    strength: float


class WriterResult(BaseModel):
    body: str
    citations: list[CitationOut]
    tokens_in: int
    tokens_out: int


class WriterAgent(Agent[WriterGoal, WriterResult]):
    @property
    def id(self) -> AgentID:
        return AgentID("Writer")

    @property
    def description(self) -> str:
        return "Writer (auction-selected) producing draft + grounded citations."

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: WriterGoal, context: AgentContext) -> AgentResult[WriterResult]:
        # auction event stream: 2 candidates compete on fitness × (1 - load)
        for name, fit, load, score in (("Writer.fast", 0.82, 0.05, 0.78), ("Writer.careful", 0.81, 0.64, 0.29)):
            await _emit(context, "auction.bid", {"candidate": name, "fitness": fit, "load": load, "score": score}, "Writer")
        await _emit(context, "auction.award", {"winner": "Writer.fast", "saved_p95_ms": 1400}, "Writer")
        await asyncio.sleep(0.32)
        cites = [
            CitationOut(claim=goal.findings[0], src="rfc-8446", supported=True, strength=0.92),
            CitationOut(claim=goal.findings[1], src="memory:research#3", supported=True, strength=0.88),
            CitationOut(claim=goal.findings[2], src="cloudflare-blog-2018", supported=True, strength=0.81),
        ]
        for c in cites:
            await _emit(context, "citation.added", c.model_dump(), "Writer")
        return AgentResult.ok(
            output=WriterResult(body="TLS 1.3 reduces handshake to 1-RTT…", citations=cites, tokens_in=248, tokens_out=64),
            state=AgentState(),
        )


# ---------- Step 6: eval gate ----------


class GateGoal(BaseModel):
    body: str


class GateResult(BaseModel):
    composite: float
    verdict: str


class GateAgent(Agent[GateGoal, GateResult]):
    """Quality gate — composite over deterministic / semantic / judge / citation."""

    @property
    def id(self) -> AgentID:
        return AgentID("Gate")

    @property
    def description(self) -> str:
        return "Composite quality gate (4 sub-scores, weighted)."

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: GateGoal, context: AgentContext) -> AgentResult[GateResult]:
        sub = {"deterministic": 1.0, "semantic": 0.91, "judge": 0.81, "citation_membership": 1.0}
        composite = round(0.2 * sub["deterministic"] + 0.4 * sub["semantic"] + 0.3 * sub["judge"] + 0.1 * sub["citation_membership"], 3)
        verdict = "pass" if composite >= 0.80 else "fail"
        await _emit(context, "eval.completed", {"composite": composite, "threshold": 0.80, "sub": sub, "verdict": verdict}, "QualityGate")
        return AgentResult.ok(output=GateResult(composite=composite, verdict=verdict), state=AgentState())


# ---------- Step 7: full flow with publisher + harvest ----------


class PublishGoal(BaseModel):
    body: str


class PublishResult(BaseModel):
    artifact_id: str


class PublisherAgent(Agent[PublishGoal, PublishResult]):
    @property
    def id(self) -> AgentID:
        return AgentID("Publisher")

    @property
    def description(self) -> str:
        return "Emits artifact, promotes session memory → PROJECT, harvests blueprint."

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: PublishGoal, context: AgentContext) -> AgentResult[PublishResult]:
        await asyncio.sleep(0.06)
        await _emit(context, "content.published", {"artifact_id": "tls-1-3-brief", "len_chars": len(goal.body)}, "Publisher")
        await _emit(context, "memory.extracted", {"tier": "PROJECT", "items": 4, "scope": "session→project"}, "Publisher")
        await _emit(context, "blueprint.harvested", {"new_blueprint_id": "research-publish-v4", "score": 0.86}, "Publisher")
        return AgentResult.ok(output=PublishResult(artifact_id="tls-1-3-brief"), state=AgentState())


# ---------- step runners ----------


async def _run(*, registry: AgentRegistry, dag: DAG, step: int, label: str) -> Path:
    bus = InMemoryEventBus()
    tracer = RunTracer()
    tracer.attach(bus)
    services = RuntimeServices(event_bus=bus)
    config = ExecutorConfig()
    executor = create_executor(agent_registry=registry, services=services, config=config)
    result = await executor.run(dag=dag)
    print(f"step {step:>1}  {label:<32}  status={result.status.value}  events={len(tracer.events)}")
    path = _write(tracer, step=step, label=label, dag_name=dag.name)
    return path


def _r(reg: AgentRegistry, agent: Agent, goal_type: type[BaseModel]) -> AgentRegistry:
    reg.register_agent(agent_instance=agent, goal_type=goal_type)
    return reg


async def step1_hello() -> Path:
    reg = _r(AgentRegistry(), GreeterAgent(), TextGoal)
    dag = DAG(name="hello").add_node(
        node=Node.agent(id="greet", name="Greeter", agent_id="Greeter", input_mapping={"text": "world"}, output_key="greeting")
    )
    return await _run(registry=reg, dag=dag, step=1, label="hello — single agent")


async def step2_chain() -> Path:
    reg = _r(_r(AgentRegistry(), GreeterAgent(), TextGoal), UpperAgent(), TextGoal)
    dag = (
        DAG(name="chain")
        .add_node(node=Node.agent(id="greet", name="Greeter", agent_id="Greeter", input_mapping={"text": "world"}, output_key="greeting"))
        .add_node(node=Node.agent(id="upper", name="Upper", agent_id="Upper", input_mapping={"text": "$$greeting.text$$"}, output_key="loud"))
    )
    dag = dag.add_edge(edge=Edge(source="greet", target="upper"))
    return await _run(registry=reg, dag=dag, step=2, label="chain — 2 agents")


async def step3_parallel() -> Path:
    reg = AgentRegistry()
    _r(reg, FetcherA(), TextGoal)
    _r(reg, FetcherB(), TextGoal)
    _r(reg, JoinerAgent(), ListGoal)
    dag = (
        DAG(name="parallel")
        .add_node(node=Node.agent(id="seed", name="Greeter", agent_id="Greeter", input_mapping={"text": "x"}, output_key="seed"))
        .add_node(node=Node.agent(id="a", name="FetcherA", agent_id="FetcherA", input_mapping={"text": "$$seed.text$$"}, output_key="a"))
        .add_node(node=Node.agent(id="b", name="FetcherB", agent_id="FetcherB", input_mapping={"text": "$$seed.text$$"}, output_key="b"))
        .add_node(node=Node.agent(id="join", name="Joiner", agent_id="Joiner",
                                  input_mapping={"items": ["$$a.text$$", "$$b.text$$"]}, output_key="merged"))
    )
    _r(reg, GreeterAgent(), TextGoal)
    dag = dag.add_edge(edge=Edge(source="seed", target="a")).add_edge(edge=Edge(source="seed", target="b"))
    dag = dag.add_edge(edge=Edge(source="a", target="join")).add_edge(edge=Edge(source="b", target="join"))
    return await _run(registry=reg, dag=dag, step=3, label="parallel — fan-out + fan-in")


async def step4_council() -> Path:
    reg = AgentRegistry()
    _r(reg, GreeterAgent(), TextGoal)  # provides initial findings string
    _r(reg, CouncilAgent(), CouncilGoal)
    dag = (
        DAG(name="council")
        .add_node(node=Node.agent(id="seed", name="Greeter", agent_id="Greeter", input_mapping={"text": "TLS 1.3"}, output_key="seed"))
        .add_node(node=Node.agent(id="vote", name="Council", agent_id="Council",
                                  input_mapping={"findings": ["1-RTT handshake", "browser support 2018", "perf gains"]},
                                  output_key="vote"))
    )
    dag = dag.add_edge(edge=Edge(source="seed", target="vote"))
    return await _run(registry=reg, dag=dag, step=4, label="council — 3-member vote")


async def step5_auction_writer() -> Path:
    reg = AgentRegistry()
    _r(reg, GreeterAgent(), TextGoal)
    _r(reg, WriterAgent(), WriterGoal)
    dag = (
        DAG(name="auction_writer")
        .add_node(node=Node.agent(id="seed", name="Greeter", agent_id="Greeter", input_mapping={"text": "TLS"}, output_key="seed"))
        .add_node(node=Node.agent(id="write", name="Writer", agent_id="Writer",
                                  input_mapping={"findings": ["1-RTT handshake", "browser support 2018", "perf gains"]},
                                  output_key="draft"))
    )
    dag = dag.add_edge(edge=Edge(source="seed", target="write"))
    return await _run(registry=reg, dag=dag, step=5, label="auction + writer — competitive selection")


async def step6_gate() -> Path:
    reg = AgentRegistry()
    _r(reg, WriterAgent(), WriterGoal)
    _r(reg, GateAgent(), GateGoal)
    dag = (
        DAG(name="gate")
        .add_node(node=Node.agent(id="write", name="Writer", agent_id="Writer",
                                  input_mapping={"findings": ["a", "b", "c"]}, output_key="draft"))
        .add_node(node=Node.agent(id="gate", name="QualityGate", agent_id="Gate",
                                  input_mapping={"body": "$$draft.body$$"}, output_key="verdict"))
    )
    dag = dag.add_edge(edge=Edge(source="write", target="gate"))
    return await _run(registry=reg, dag=dag, step=6, label="quality gate — composite eval")


async def step7_full() -> Path:
    reg = AgentRegistry()
    _r(reg, GreeterAgent(), TextGoal)
    _r(reg, CouncilAgent(), CouncilGoal)
    _r(reg, WriterAgent(), WriterGoal)
    _r(reg, GateAgent(), GateGoal)
    _r(reg, PublisherAgent(), PublishGoal)
    dag = (
        DAG(name="full_flow")
        .add_node(node=Node.agent(id="seed", name="Greeter", agent_id="Greeter", input_mapping={"text": "TLS 1.3"}, output_key="seed"))
        .add_node(node=Node.agent(id="vote", name="Council", agent_id="Council",
                                  input_mapping={"findings": ["1-RTT handshake", "browser support 2018", "perf gains"]},
                                  output_key="vote"))
        .add_node(node=Node.agent(id="write", name="Writer", agent_id="Writer",
                                  input_mapping={"findings": ["1-RTT handshake", "browser support 2018", "perf gains"]},
                                  output_key="draft"))
        .add_node(node=Node.agent(id="gate", name="QualityGate", agent_id="Gate",
                                  input_mapping={"body": "$$draft.body$$"}, output_key="verdict"))
        .add_node(node=Node.agent(id="pub", name="Publisher", agent_id="Publisher",
                                  input_mapping={"body": "$$draft.body$$"}, output_key="published"))
    )
    dag = dag.add_edge(edge=Edge(source="seed", target="vote"))
    dag = dag.add_edge(edge=Edge(source="vote", target="write"))
    dag = dag.add_edge(edge=Edge(source="write", target="gate"))
    dag = dag.add_edge(edge=Edge(source="gate", target="pub"))
    return await _run(registry=reg, dag=dag, step=7, label="full flow — research→vote→write→gate→publish")


STEPS = {
    1: step1_hello,
    2: step2_chain,
    3: step3_parallel,
    4: step4_council,
    5: step5_auction_writer,
    6: step6_gate,
    7: step7_full,
}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", type=int, choices=sorted(STEPS), help="Run a single step (default: all)")
    args = parser.parse_args()

    targets = [args.step] if args.step else sorted(STEPS)
    written: list[Path] = []
    for step in targets:
        path = await STEPS[step]()
        written.append(path)

    # Index file so the viz can list all available steps without sniffing
    idx = {
        "schema_version": 1,
        "steps": [
            {
                "step": s,
                "label": (await asyncio.to_thread(_label_of, s)),
                "path": f"traces/step-{s}.json",
            }
            for s in sorted(STEPS)
            if (TRACE_DIR / f"step-{s}.json").exists()
        ],
    }
    (TRACE_DIR / "index.json").write_text(json.dumps(idx, indent=2))
    print()
    for p in written:
        print(f"  → {p.relative_to(REPO_ROOT)}")


def _label_of(step: int) -> str:
    # we don't have the label without running, so re-encode known labels
    return {
        1: "hello — single agent",
        2: "chain — 2 agents",
        3: "parallel — fan-out + fan-in",
        4: "council — 3-member vote",
        5: "auction + writer — competitive selection",
        6: "quality gate — composite eval",
        7: "full flow — research→vote→write→gate→publish",
    }[step]


if __name__ == "__main__":
    asyncio.run(main())
