"""CEMAF benchmark and veracity harness.

Run:
    uv run python benchmarks/run_benchmarks.py

Generate durable local evidence:
    uv run python benchmarks/run_benchmarks.py \
        --json-out benchmarks/results/local-baseline.json \
        --markdown-out benchmarks/results/local-baseline.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import platform
import re
import statistics
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from cemaf import DAG, AgentRegistry, Edge, Node, create_executor
from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.agents.selection import Capability, DefaultAgentSelector
from cemaf.blueprint import BlueprintLibrary, InMemoryWritableBlueprintSource, create_blueprint_harvester
from cemaf.citation.tracker import CitationTracker
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import CompiledContext, PriorityContextCompiler, SimpleTokenEstimator
from cemaf.context.context import Context
from cemaf.context.patch import ContextPatch, PatchOperation, PatchSource
from cemaf.context.source import ContextSource
from cemaf.core.enums import NodeType
from cemaf.core.result import Result
from cemaf.core.types import AgentID, FinishReason, NodeID, RunID, TokenCount, ToolID
from cemaf.evals.evaluators import LengthEvaluator
from cemaf.evals.police import QualityPolice, QualityPoliceConfig
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType
from cemaf.interceptors import GateEvalInterceptor, create_interceptor_pipeline
from cemaf.llm.protocols import CompletionResult, LLMConfig, Message, StreamChunk, ToolDefinition
from cemaf.observability.budget_guard import BudgetGuard
from cemaf.orchestration.dag import Condition, ConditionOperator, EdgeCondition
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices
from cemaf.retrieval.protocols import Document, SearchResult
from cemaf.rlm import create_rlm_tool
from cemaf.skills.base import Skill
from cemaf.tools.base import Tool, ToolResult, ToolSchema

SyncBenchmark = Callable[[], None]
AsyncBenchmark = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class BenchmarkResult:
    """Aggregated latency and throughput for one benchmark subject."""

    name: str
    category: str
    iterations: int
    repetitions: int
    warmup: int
    total_ms: float
    mean_ms: float
    median_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float
    ops_per_sec: float
    samples_ms: tuple[float, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "iterations": self.iterations,
            "repetitions": self.repetitions,
            "warmup": self.warmup,
            "total_ms": round(self.total_ms, 6),
            "mean_ms": round(self.mean_ms, 6),
            "median_ms": round(self.median_ms, 6),
            "p95_ms": round(self.p95_ms, 6),
            "min_ms": round(self.min_ms, 6),
            "max_ms": round(self.max_ms, 6),
            "ops_per_sec": round(self.ops_per_sec, 3),
            "samples_ms": [round(v, 6) for v in self.samples_ms],
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class VeracityCheck:
    """A README/doc check tied to executable evidence."""

    check_id: str
    statement: str
    source: str
    evidence: str
    passed: bool
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "statement": self.statement,
            "source": self.source,
            "evidence": self.evidence,
            "passed": self.passed,
            "metrics": self.metrics,
        }


class BenchGoal(BaseModel):
    value: int = 0


class BenchResult(BaseModel):
    output: int = 0


class TagGoal(BaseModel):
    tag: str


class TagResult(BaseModel):
    tag: str
    run_id: str


class WriteGoal(BaseModel):
    objective: str = "write"


class WriteResult(BaseModel):
    article: str


class NoOpAgent(Agent[BenchGoal, BenchResult]):
    """Small registered agent for executor benchmarks."""

    def __init__(self) -> None:
        self.run_count = 0

    @property
    def id(self) -> AgentID:
        return AgentID("bench_agent")

    @property
    def description(self) -> str:
        return "Benchmark no-op agent"

    @property
    def skills(self) -> tuple[Skill[Any, Any], ...]:
        return ()

    async def run(self, goal: BenchGoal, context: AgentContext) -> AgentResult[BenchResult]:
        self.run_count += 1
        return AgentResult.ok(output=BenchResult(output=goal.value + 1), state=AgentState())


class YieldingTagAgent(Agent[TagGoal, TagResult]):
    """Agent that forces async interleaving and echoes per-run state."""

    @property
    def id(self) -> AgentID:
        return AgentID("bench_tag_agent")

    @property
    def description(self) -> str:
        return "Echoes tag and run ID after an async hop"

    @property
    def skills(self) -> tuple[Skill[Any, Any], ...]:
        return ()

    async def run(self, goal: TagGoal, context: AgentContext) -> AgentResult[TagResult]:
        await asyncio.sleep(0)
        return AgentResult.ok(output=TagResult(tag=goal.tag, run_id=context.run_id), state=AgentState())


class WriteLoadAgent(Agent[WriteGoal, WriteResult]):
    """WRITE-capable agent with deterministic load for auction checks."""

    def __init__(self, agent_id: str, load: float, *, ran: list[str]) -> None:
        self._id = AgentID(agent_id)
        self._load = load
        self._ran = ran

    @property
    def id(self) -> AgentID:
        return self._id

    @property
    def description(self) -> str:
        return f"writer {self._id}"

    @property
    def skills(self) -> tuple[Skill[Any, Any], ...]:
        return ()

    @property
    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.WRITE})

    @property
    def current_load(self) -> float:
        return self._load

    async def run(self, goal: WriteGoal, context: AgentContext) -> AgentResult[WriteResult]:
        self._ran.append(str(self._id))
        return AgentResult.ok(
            output=WriteResult(article=f"written-by:{self._id}:{goal.objective}"),
            state=AgentState(),
        )


class CouncilVoteAgent(Agent[BenchGoal, str]):
    """Agent that also implements the CouncilMember deliberate() protocol."""

    def __init__(self, agent_id: str, choice: str) -> None:
        self._id = AgentID(agent_id)
        self._choice = choice

    @property
    def id(self) -> AgentID:
        return self._id

    @property
    def description(self) -> str:
        return f"votes {self._choice}"

    @property
    def skills(self) -> tuple[Skill[Any, Any], ...]:
        return ()

    async def run(self, goal: BenchGoal, context: AgentContext) -> AgentResult[str]:
        return AgentResult.ok(output=self._choice, state=AgentState())

    async def deliberate(self, *, question: object, goal: object, context: AgentContext) -> Any:
        from cemaf.council.types import Opinion

        await asyncio.sleep(0)
        return Opinion(member_id=self._id, choice=self._choice)


class GateTextAgent(Agent[BenchGoal, str]):
    """Generator/consumer agent for GATE interceptor checks."""

    def __init__(self, agent_id: str, text: str, *, ran: list[str] | None = None) -> None:
        self._id = AgentID(agent_id)
        self._text = text
        self._ran = ran
        self.runs = 0

    @property
    def id(self) -> AgentID:
        return self._id

    @property
    def description(self) -> str:
        return f"gate text agent {self._id}"

    @property
    def skills(self) -> tuple[Skill[Any, Any], ...]:
        return ()

    async def run(self, goal: BenchGoal, context: AgentContext) -> AgentResult[str]:
        self.runs += 1
        if self._ran is not None:
            self._ran.append(str(self._id))
        return AgentResult.ok(output=self._text, state=AgentState())


class RequiredNoOpTool(Tool):
    """Tool for validated_execute() overhead and contract checks."""

    @property
    def id(self) -> ToolID:
        return ToolID("bench_tool")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="bench_tool",
            description="No-op benchmark tool",
            parameters={
                "type": "object",
                "properties": {"value": {"type": "integer"}},
            },
            required=("value",),
            is_concurrent_safe=True,
            is_read_only=True,
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        return Result.ok(data={"ok": True, "value": kwargs["value"]})


class CountingLLMClient:
    """LLM client that records calls and returns a deterministic response."""

    def __init__(self, model: str = "counting-mock") -> None:
        self._model = model
        self.call_count = 0
        self.prompts: list[str] = []

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(model=self._model, temperature=0.0)

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
        *,
        fidelity: object | None = None,
        token_budget: object | None = None,
        correlation_id: str | None = None,
    ) -> CompletionResult:
        self.call_count += 1
        prompt = "\n".join(str(message.content) for message in messages)
        self.prompts.append(prompt)
        return CompletionResult.ok(
            message=Message.assistant("deterministic answer"),
            prompt_tokens=max(1, len(prompt) // 4),
            completion_tokens=3,
            model=self._model,
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(
            content="deterministic answer",
            accumulated_content="deterministic answer",
            is_final=True,
            finish_reason=FinishReason.TERMINAL_STOP,
        )

    def count_tokens(self, text: str) -> TokenCount:
        return TokenCount(max(1, len(text) // 4))

    def count_messages_tokens(self, messages: list[Message]) -> TokenCount:
        return TokenCount(sum(int(self.count_tokens(str(message.content))) for message in messages))

    async def count_tokens_exact(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> TokenCount:
        return self.count_messages_tokens(messages)


class CorpusLLMClient(CountingLLMClient):
    """Deterministic client for RLM corpus accuracy checks."""

    def __init__(self, answers: dict[str, str]) -> None:
        super().__init__(model="corpus-mock")
        self._answers = answers

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
        *,
        fidelity: object | None = None,
        token_budget: object | None = None,
        correlation_id: str | None = None,
    ) -> CompletionResult:
        self.call_count += 1
        prompt = "\n".join(str(message.content) for message in messages)
        self.prompts.append(prompt)
        await asyncio.sleep(0)

        match = re.search(r"question\s+(q\d{2})", prompt, flags=re.IGNORECASE)
        content = "NOT_FOUND"
        if match:
            question_id = match.group(1).lower()
            answer = self._answers.get(question_id)
            source_pattern = re.compile(
                rf"QUESTION_ID={re.escape(question_id)}\s+ANSWER={re.escape(answer or '')}\b",
                flags=re.IGNORECASE,
            )
            aggregation_prompt = "I have gathered information" in prompt or "Synthesize these" in prompt
            if answer and (source_pattern.search(prompt) or (aggregation_prompt and answer in prompt)):
                content = answer
            else:
                content = f"NOT_FOUND:{question_id}"

        return CompletionResult.ok(
            message=Message.assistant(content),
            prompt_tokens=max(1, len(prompt) // 4),
            completion_tokens=max(1, len(content) // 4),
            model=self.config.model,
        )


def _percentile(values: tuple[float, ...], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    fraction = rank - low
    return ordered[low] + (ordered[high] - ordered[low]) * fraction


def _summarize_samples(
    *,
    name: str,
    category: str,
    iterations: int,
    repetitions: int,
    warmup: int,
    samples_ms: list[float],
    total_ms: float,
    metadata: dict[str, Any] | None = None,
) -> BenchmarkResult:
    sample_tuple = tuple(samples_ms)
    mean_ms = statistics.fmean(sample_tuple) if sample_tuple else 0.0
    return BenchmarkResult(
        name=name,
        category=category,
        iterations=iterations,
        repetitions=repetitions,
        warmup=warmup,
        total_ms=total_ms,
        mean_ms=mean_ms,
        median_ms=statistics.median(sample_tuple) if sample_tuple else 0.0,
        p95_ms=_percentile(sample_tuple, 0.95),
        min_ms=min(sample_tuple) if sample_tuple else 0.0,
        max_ms=max(sample_tuple) if sample_tuple else 0.0,
        ops_per_sec=(1000.0 / mean_ms) if mean_ms > 0 else 0.0,
        samples_ms=sample_tuple,
        metadata=metadata or {},
    )


def bench_sync(
    name: str,
    category: str,
    iterations: int,
    fn: SyncBenchmark,
    *,
    repetitions: int = 5,
    warmup: int = 1,
    metadata: dict[str, Any] | None = None,
) -> BenchmarkResult:
    for _ in range(warmup):
        fn()

    samples: list[float] = []
    total_ms = 0.0
    for _ in range(repetitions):
        start = time.perf_counter()
        for _ in range(iterations):
            fn()
        elapsed_ms = (time.perf_counter() - start) * 1000
        total_ms += elapsed_ms
        samples.append(elapsed_ms / iterations)

    return _summarize_samples(
        name=name,
        category=category,
        iterations=iterations,
        repetitions=repetitions,
        warmup=warmup,
        samples_ms=samples,
        total_ms=total_ms,
        metadata=metadata,
    )


async def bench_async(
    name: str,
    category: str,
    iterations: int,
    fn: AsyncBenchmark,
    *,
    repetitions: int = 5,
    warmup: int = 1,
    metadata: dict[str, Any] | None = None,
) -> BenchmarkResult:
    for _ in range(warmup):
        await fn()

    samples: list[float] = []
    total_ms = 0.0
    for _ in range(repetitions):
        start = time.perf_counter()
        for _ in range(iterations):
            await fn()
        elapsed_ms = (time.perf_counter() - start) * 1000
        total_ms += elapsed_ms
        samples.append(elapsed_ms / iterations)

    return _summarize_samples(
        name=name,
        category=category,
        iterations=iterations,
        repetitions=repetitions,
        warmup=warmup,
        samples_ms=samples,
        total_ms=total_ms,
        metadata=metadata,
    )


def _create_agent_executor(
    *,
    services: RuntimeServices | None = None,
) -> tuple[NoOpAgent, Any]:
    agent = NoOpAgent()
    registry = AgentRegistry()
    registry.register_agent(agent_instance=agent, goal_type=BenchGoal)
    executor = create_executor(
        agent_registry=registry,
        services=services,
        config=ExecutorConfig(enable_logging=False, enable_events=services is not None),
    )
    return agent, executor


def _agent_dag(name: str = "bench", nodes: int = 1, *, structured_output: bool = False) -> DAG:
    dag = DAG(name=name, description="benchmark")
    previous: str | None = None
    for i in range(nodes):
        node = Node(
            id=NodeID(f"a{i}"),
            type=NodeType.AGENT,
            name=f"A{i}",
            ref_id="bench_agent",
            input_mapping={"value": "$$value$$"} if i == 0 else {},
            output_key=f"out{i}",
            structured_output=structured_output,
        )
        dag = dag.add_node(node)
        if previous is not None:
            dag = dag.add_edge(Edge(source=NodeID(previous), target=NodeID(f"a{i}")))
        previous = f"a{i}"
    return dag


def _tag_router_dag() -> DAG:
    router = Node(
        id=NodeID("route"),
        type=NodeType.ROUTER,
        name="route",
        config={"route_key": "branch"},
        routes={"left": "left", "right": "right"},
        output_key="route_targets",
    )
    left = Node(
        id=NodeID("left"),
        type=NodeType.AGENT,
        name="left",
        ref_id="bench_tag_agent",
        input_mapping={"tag": "$$tag$$"},
        output_key="tag_out",
        structured_output=True,
    )
    right = Node(
        id=NodeID("right"),
        type=NodeType.AGENT,
        name="right",
        ref_id="bench_tag_agent",
        input_mapping={"tag": "$$tag$$"},
        output_key="tag_out",
        structured_output=True,
    )
    return DAG(
        name="bench-router-concurrency",
        nodes=(router, left, right),
        edges=(
            Edge(source=NodeID("route"), target=NodeID("left")),
            Edge(source=NodeID("route"), target=NodeID("right")),
        ),
        entry_node=NodeID("route"),
    )


def _gate_dag(*, retry: bool = True) -> DAG:
    gen = Node(
        id=NodeID("gen"),
        type=NodeType.AGENT,
        name="gen",
        ref_id="gen",
        output_key="draft",
        retry_on_failure=retry,
        max_retries=3,
    )
    use = Node.agent(id="use", name="use", agent_id="use", output_key="final")
    return DAG(
        name="bench-gate",
        nodes=(gen, use),
        edges=(Edge(source=NodeID("gen"), target=NodeID("use"), condition=EdgeCondition.ON_SUCCESS),),
        entry_node=NodeID("gen"),
    )


async def _publish_blueprint_run(
    *,
    bus: InMemoryEventBus,
    run_id: str,
    node_id: str,
    goal_text: str,
    output: str,
    score: float,
) -> None:
    for event in (
        Event.create(
            type=EventType.TASK_STARTED,
            payload={
                "run_id": run_id,
                "node_id": node_id,
                "goal_text": goal_text,
                "inputs": {"objective": goal_text},
            },
            correlation_id=run_id,
        ),
        Event.create(
            type=EventType.TASK_COMPLETED,
            payload={"run_id": run_id, "node_id": node_id, "output": output, "success": True},
            correlation_id=run_id,
        ),
        Event.create(
            type=EventType.EVAL_COMPLETED,
            payload={
                "run_id": run_id,
                "node_id": node_id,
                "overall_score": score,
                "overall_passed": True,
                "results": [],
            },
            correlation_id=run_id,
        ),
    ):
        await bus.publish(event)


def bench_dag_construction(scale: int) -> BenchmarkResult:
    def build_once() -> None:
        dag = DAG(name="bench", description="construction benchmark")
        for i in range(20):
            dag = dag.add_node(Node.agent(id=f"n{i}", name=f"N{i}", agent_id=f"a{i}", output_key=f"o{i}"))
        for i in range(19):
            dag = dag.add_edge(Edge(source=NodeID(f"n{i}"), target=NodeID(f"n{i + 1}")))
        dag.validate_structure()

    return bench_sync(
        "DAG construction (20 nodes)",
        "orchestration",
        iterations=300 * scale,
        fn=build_once,
        metadata={"nodes": 20, "edges": 19},
    )


def bench_quality_police_scoring(scale: int) -> BenchmarkResult:
    police = QualityPolice(
        config=QualityPoliceConfig(
            window_size=50,
            predictive_halt_enabled=True,
            min_samples_for_trend=4,
        )
    )
    scores = [0.8 + ((i % 17) - 8) / 100 for i in range(100)]
    idx = 0

    def record_once() -> None:
        nonlocal idx
        police.record_score(score=scores[idx % len(scores)])
        idx += 1

    return bench_sync(
        "QualityPolice scoring + trend",
        "evals",
        iterations=2000 * scale,
        fn=record_once,
        metadata={"window_size": 50, "samples_cycle": len(scores)},
    )


def bench_context_patch_apply(scale: int) -> BenchmarkResult:
    index = 0

    def apply_once() -> None:
        nonlocal index
        context = Context()
        context = context.apply(
            ContextPatch.from_tool(
                "bench_tool",
                "payload.value",
                index,
                reason="benchmark patch",
            )
        )
        if context.get("payload.value") != index:
            raise AssertionError("Context patch failed to apply")
        index += 1

    return bench_sync(
        "Context patch apply + provenance",
        "context",
        iterations=2000 * scale,
        fn=apply_once,
        metadata={"patches_per_iteration": 1},
    )


async def bench_tool_validated_execute(scale: int) -> BenchmarkResult:
    tool = RequiredNoOpTool()

    async def execute_once() -> None:
        result = await tool.validated_execute(value=1)
        if not result.success:
            raise AssertionError(result.error or "tool failed")

    return await bench_async(
        "Tool validated_execute()",
        "tools",
        iterations=2000 * scale,
        fn=execute_once,
        metadata={"required_params": len(tool.schema.required)},
    )


async def bench_dag_execution_1_node(scale: int) -> BenchmarkResult:
    _, executor = _create_agent_executor()
    dag = _agent_dag(nodes=1)

    async def run_once() -> None:
        result = await executor.run(dag=dag, initial_context=Context(data={"value": 1}))
        if not result.success:
            raise AssertionError(result.error or "DAG failed")

    return await bench_async(
        "DAG execution (1 agent node)",
        "orchestration",
        iterations=100 * scale,
        fn=run_once,
        metadata={"nodes": 1},
    )


async def bench_dag_execution_5_node_chain(scale: int) -> BenchmarkResult:
    _, executor = _create_agent_executor()
    dag = _agent_dag(name="bench5", nodes=5)

    async def run_once() -> None:
        result = await executor.run(dag=dag, initial_context=Context(data={"value": 1}))
        if not result.success:
            raise AssertionError(result.error or "DAG failed")

    return await bench_async(
        "DAG execution (5 agent chain)",
        "orchestration",
        iterations=50 * scale,
        fn=run_once,
        metadata={"nodes": 5, "edges": 4},
    )


async def bench_context_compilation(scale: int) -> BenchmarkResult:
    estimator = SimpleTokenEstimator()
    compiler = PriorityContextCompiler(token_estimator=estimator)
    budget = TokenBudget(max_tokens=10_000)
    artifacts = tuple((f"doc_{i}", f"Content for document {i} " * 20) for i in range(50))
    memories = tuple((f"mem_{i}", f"Memory item {i} " * 10) for i in range(20))

    async def compile_once() -> None:
        compiled = await compiler.compile(artifacts=artifacts, memories=memories, budget=budget)
        if not compiled.sources:
            raise AssertionError("No context sources selected")

    return await bench_async(
        "Context compilation (70 sources)",
        "context",
        iterations=200 * scale,
        fn=compile_once,
        metadata={"sources": len(artifacts) + len(memories), "budget_tokens": budget.max_tokens},
    )


async def bench_context_compaction(scale: int) -> BenchmarkResult:
    estimator = SimpleTokenEstimator()
    compiler = PriorityContextCompiler(token_estimator=estimator)
    budget = TokenBudget(max_tokens=10_000)
    sources = tuple(
        ContextSource(
            content=f"Source {i} content " * 50,
            token_count=TokenCount(200),
            priority=i,
            source_type="artifact",
            source_id=f"s{i}",
        )
        for i in range(10)
    )
    compiled = CompiledContext(sources=sources, total_tokens=2000, budget=budget)

    async def compact_once() -> None:
        compacted = await compiler.compact(compiled=compiled, preserve_recent=2, summary_budget_tokens=500)
        if not compacted.sources:
            raise AssertionError("Compaction returned no sources")

    return await bench_async(
        "Context compaction (10 sources)",
        "context",
        iterations=200 * scale,
        fn=compact_once,
        metadata={"sources": len(sources), "preserve_recent": 2},
    )


async def bench_event_bus_pubsub(scale: int) -> BenchmarkResult:
    bus = InMemoryEventBus()
    received = 0

    async def handler(event: Event) -> None:
        nonlocal received
        if event.type != EventType.TASK_COMPLETED.value:
            raise AssertionError(f"Unexpected event type: {event.type}")
        received += 1

    bus.subscribe(event_type=EventType.TASK_COMPLETED, handler=handler)

    async def publish_once() -> None:
        await bus.publish(
            event=Event.create(
                type=EventType.TASK_COMPLETED,
                payload={"node_id": "n1", "output": "ok"},
                source="bench",
            )
        )

    result = await bench_async(
        "EventBus pub/sub",
        "events",
        iterations=1000 * scale,
        fn=publish_once,
        metadata={"subscribers": 1},
    )
    expected = result.iterations * result.repetitions + result.warmup
    if received != expected:
        raise AssertionError(f"Expected {expected} events, received {received}")
    return result


async def bench_shared_executor_concurrency(scale: int) -> BenchmarkResult:
    _, executor = _create_agent_executor()
    dag = _agent_dag(name="concurrent", nodes=1, structured_output=True)
    runs_per_batch = 32

    async def run_batch() -> None:
        async def run_one(value: int) -> int:
            result = await executor.run(dag=dag, initial_context=Context(data={"value": value}))
            if not result.success:
                raise AssertionError(result.error or "DAG failed")
            output = result.final_context.get("out0")
            if not isinstance(output, dict):
                raise AssertionError(f"Expected structured output, got {output!r}")
            return int(output["output"])

        outputs = await asyncio.gather(*(run_one(i) for i in range(runs_per_batch)))
        expected = [i + 1 for i in range(runs_per_batch)]
        if outputs != expected:
            raise AssertionError(f"Concurrent outputs leaked context: {outputs!r}")

    return await bench_async(
        "Shared executor concurrent batch (32 runs)",
        "orchestration",
        iterations=5 * scale,
        fn=run_batch,
        repetitions=3,
        metadata={"runs_per_batch": runs_per_batch},
    )


def _build_rlm_corpus() -> tuple[str, dict[str, str]]:
    answers = {f"q{i:02d}": f"answer_token_{i:02d}_cemaf_verified" for i in range(20)}
    sections: list[str] = []
    filler = " ".join(f"filler{i}" for i in range(180))
    for i in range(40):
        question_id = f"q{i:02d}" if i < 20 else f"distractor_{i:02d}"
        answer = answers.get(question_id, f"distractor_answer_{i:02d}")
        decoy_id = f"q{i % 20:02d}"
        decoy = answers[decoy_id] if i >= 20 else f"near_match_{i:02d}"
        sections.append(
            "\n".join(
                (
                    f"SECTION {i:02d}",
                    f"QUESTION_ID={question_id} ANSWER={answer}",
                    f"DECOY_REF_FOR={decoy_id} WRONG_ANSWER={decoy}",
                    f"BODY {filler}",
                )
            )
        )
    return "\n\n".join(sections), answers


async def check_agent_dag_check() -> VeracityCheck:
    _, executor = _create_agent_executor()
    dag = _agent_dag(nodes=1, structured_output=True)
    runs = 25
    start = time.perf_counter()
    results = [
        await executor.run(dag=dag, initial_context=Context(data={"value": value})) for value in range(runs)
    ]
    elapsed_ms = (time.perf_counter() - start) * 1000
    outputs = [result.final_context.get("out0") for result in results]
    passed = all(result.success for result in results) and outputs == [{"output": i + 1} for i in range(runs)]
    return VeracityCheck(
        check_id="agent-dag-units-of-work",
        statement="Typed agent DAG nodes execute as isolated units of work and propagate outputs.",
        source="README.md: Overview / A different shape of agent system",
        evidence="Ran one registered Agent through create_executor() 25 times with distinct inputs.",
        passed=passed,
        metrics={
            "runs": runs,
            "successes": sum(1 for result in results if result.success),
            "elapsed_ms": round(elapsed_ms, 3),
            "avg_ms": round(elapsed_ms / runs, 3),
        },
    )


async def check_pull_cost_check() -> VeracityCheck:
    llm = CountingLLMClient()
    services = RuntimeServices(llm_client=llm)
    _, executor = _create_agent_executor(services=services)
    dag = _agent_dag(nodes=1)
    runs = 25
    start = time.perf_counter()
    results = [
        await executor.run(dag=dag, initial_context=Context(data={"value": value})) for value in range(runs)
    ]
    elapsed_ms = (time.perf_counter() - start) * 1000
    passed = all(result.success for result in results) and llm.call_count == 0
    return VeracityCheck(
        check_id="pull-cost-absent-services-do-not-run",
        statement=(
            "A deterministic registered agent run does not call an LLM just because an LLM client exists."
        ),
        source="README.md: CEMAF is PULL / services absent or unused do not run",
        evidence="Injected a CountingLLMClient into RuntimeServices and executed 25 no-op agent DAG runs.",
        passed=passed,
        metrics={
            "runs": runs,
            "llm_calls": llm.call_count,
            "elapsed_ms": round(elapsed_ms, 3),
            "avg_ms": round(elapsed_ms / runs, 3),
        },
    )


async def check_context_budget_check() -> VeracityCheck:
    estimator = SimpleTokenEstimator(chars_per_token=4.0)
    compiler = PriorityContextCompiler(token_estimator=estimator)
    budget = TokenBudget(max_tokens=500, reserved_for_output=100)
    artifacts = tuple((f"doc_{i}", f"important document {i} " * 60) for i in range(30))
    priorities = {f"doc_{i}": 100 - i for i in range(30)}
    compiled = await compiler.compile(artifacts=artifacts, memories=(), budget=budget, priorities=priorities)
    passed = compiled.within_budget() and len(compiled.sources) < len(artifacts)
    return VeracityCheck(
        check_id="context-budget-selection",
        statement="Context compilation respects TokenBudget and drops lower-priority sources when needed.",
        source="README.md: Hard Problems / Context Growth and Cost",
        evidence="Compiled 30 oversized artifacts into a 400-token available budget.",
        passed=passed,
        metrics={
            "input_sources": len(artifacts),
            "selected_sources": len(compiled.sources),
            "available_tokens": budget.available_tokens,
            "compiled_tokens": compiled.total_tokens,
            "within_budget": compiled.within_budget(),
            "selected_keys": [source.key for source in compiled.sources[:5]],
        },
    )


def check_context_provenance_check() -> VeracityCheck:
    context = Context(data={"seed": 1})
    patch_a = ContextPatch.from_tool("loader", "data.a", 1, reason="load a")
    patch_b = ContextPatch.from_agent("writer", "data.b", 2, reason="write b")
    patch_c = ContextPatch.from_tool(
        "collector",
        "items",
        "x",
        operation=PatchOperation.APPEND,
        reason="collect",
    )
    final = context.apply(patch_a).apply(patch_b).apply(patch_c)
    rolled_back = final.rollback_to(patch_b.id)
    timeline = final.get_timeline()
    passed = (
        final.get("data.a") == 1
        and final.get("data.b") == 2
        and final.get("items") == ["x"]
        and rolled_back.get("items") is None
        and len(timeline) == 3
        and timeline[0].source == PatchSource.TOOL
        and timeline[1].source == PatchSource.AGENT
    )
    return VeracityCheck(
        check_id="context-patch-provenance",
        statement="Context changes are immutable patches with source, reason, timeline, and rollback.",
        source="README.md: Immutable context with provenance",
        evidence="Applied tool and agent patches, inspected timeline, and rolled back to a prior patch ID.",
        passed=passed,
        metrics={
            "patches": len(timeline),
            "final_hash": final.state_hash()[:16],
            "rollback_hash": rolled_back.state_hash()[:16],
            "sources": [patch.source.value for patch in timeline],
        },
    )


async def check_event_bus_check() -> VeracityCheck:
    bus = InMemoryEventBus()
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(event_type=EventType.TASK_COMPLETED, handler=handler)
    events = [
        Event.create(
            type=EventType.TASK_COMPLETED,
            payload={"node_id": f"n{i}", "success": True},
            source="bench",
            correlation_id="bench-run",
        )
        for i in range(100)
    ]
    start = time.perf_counter()
    await bus.publish_batch(events)
    elapsed_ms = (time.perf_counter() - start) * 1000
    passed = len(received) == len(events) and all(event.correlation_id == "bench-run" for event in received)
    return VeracityCheck(
        check_id="typed-event-stream",
        statement="The event bus emits typed execution events with correlation metadata.",
        source="README.md: Glass-box by default / EventBus output",
        evidence="Published 100 TASK_COMPLETED events through InMemoryEventBus.publish_batch().",
        passed=passed,
        metrics={
            "published": len(events),
            "received": len(received),
            "elapsed_ms": round(elapsed_ms, 3),
            "events_per_sec": round(len(events) / (elapsed_ms / 1000), 1) if elapsed_ms > 0 else 0.0,
        },
    )


async def check_concurrency_check() -> VeracityCheck:
    registry = AgentRegistry()
    registry.register_agent(agent_instance=YieldingTagAgent(), goal_type=TagGoal)
    bus = InMemoryEventBus()
    received: list[Event] = []

    async def capture(event: Event) -> None:
        received.append(event)

    bus.subscribe_all(capture)
    executor = create_executor(
        agent_registry=registry,
        services=RuntimeServices(event_bus=bus),
        config=ExecutorConfig(enable_logging=False, enable_events=True),
    )
    dag = _tag_router_dag()
    runs = 64
    expected_run_ids = {f"bench-run-{i}" for i in range(runs)}

    async def run_one(value: int) -> tuple[str, str, str]:
        branch = "left" if value % 2 == 0 else "right"
        run_id = RunID(f"bench-run-{value}")
        result = await executor.run(
            dag=dag,
            initial_context=Context(data={"tag": f"tag-{value}", "branch": branch}),
            run_id=run_id,
        )
        if not result.success:
            return (str(run_id), branch, "FAILED")
        output = result.final_context.get("tag_out")
        if not isinstance(output, dict):
            return (str(run_id), branch, "MISSING")
        executed_node_ids = {str(node_result.node_id) for node_result in result.node_results}
        branch_ok = branch in executed_node_ids and ({"left", "right"} - {branch}).isdisjoint(
            executed_node_ids
        )
        if output.get("tag") != f"tag-{value}" or not branch_ok:
            return (str(run_id), branch, str(output))
        return (str(run_id), branch, "OK")

    start = time.perf_counter()
    outputs = await asyncio.gather(*(run_one(i) for i in range(runs)))
    elapsed_ms = (time.perf_counter() - start) * 1000
    mismatches = sum(1 for _, _, status in outputs if status != "OK")
    wrong_correlation_events = sum(
        1
        for event in received
        if event.correlation_id is not None and event.correlation_id not in expected_run_ids
    )
    dag_completed_ids = {
        event.correlation_id for event in received if event.type == EventType.DAG_COMPLETED.value
    }
    missing_completed_ids = expected_run_ids - {item for item in dag_completed_ids if item is not None}
    return VeracityCheck(
        check_id="shared-executor-concurrency-isolation",
        statement=(
            "Concurrent calls on one DAGExecutor keep per-run routes, context, "
            "and event correlation isolated."
        ),
        source="README.md: Concurrent-Run Contamination",
        evidence=(
            "Ran 64 concurrent router DAG calls through one executor with explicit "
            "run IDs and EventBus capture."
        ),
        passed=mismatches == 0 and wrong_correlation_events == 0 and not missing_completed_ids,
        metrics={
            "runs": runs,
            "mismatches": mismatches,
            "captured_events": len(received),
            "wrong_correlation_events": wrong_correlation_events,
            "missing_dag_completed_events": len(missing_completed_ids),
            "elapsed_ms": round(elapsed_ms, 3),
            "runs_per_sec": round(runs / (elapsed_ms / 1000), 1) if elapsed_ms > 0 else 0.0,
        },
    )


async def check_auction_selection_check() -> VeracityCheck:
    ran: list[str] = []
    registry = AgentRegistry()
    registry.register_agent(
        agent_instance=WriteLoadAgent("WriterBusy", load=0.9, ran=ran),
        goal_type=WriteGoal,
        capabilities=frozenset({Capability.WRITE}),
    )
    registry.register_agent(
        agent_instance=WriteLoadAgent("WriterIdle", load=0.1, ran=ran),
        goal_type=WriteGoal,
        capabilities=frozenset({Capability.WRITE}),
    )
    executor = create_executor(
        agent_registry=registry,
        services=RuntimeServices(
            agent_selector=DefaultAgentSelector(),
            budget_guard=BudgetGuard(max_cost_usd=10.0, max_total_tokens=100_000),
        ),
        config=ExecutorConfig(enable_logging=False, enable_events=False),
    )
    node = Node.auction(
        id="write",
        name="write",
        capability=Capability.WRITE.value,
        input_mapping={"objective": "draft benchmark evidence"},
        output_key="article",
    )
    dag = DAG(name="bench-auction", nodes=(node,), edges=(), entry_node=node.id)

    start = time.perf_counter()
    result = await executor.run(dag=dag)
    elapsed_ms = (time.perf_counter() - start) * 1000
    node_result = next((item for item in result.node_results if item.node_id == NodeID("write")), None)
    selection = node_result.metadata.get("selection", {}) if node_result is not None else {}
    candidate_count = len(registry.get_candidates(capability=Capability.WRITE))
    passed = (
        result.success
        and node_result is not None
        and node_result.success
        and candidate_count == 2
        and selection.get("agent_id") == "WriterIdle"
        and ran == ["WriterIdle"]
    )
    return VeracityCheck(
        check_id="auction-selects-low-load-agent",
        statement=(
            "Auction selection chooses among capable agents by deterministic bid "
            "metadata and only runs the winner."
        ),
        source="README.md: Hard problems table / Auction selection",
        evidence=("Ran a Node.auction DAG with two WRITE-capable agents and a wired DefaultAgentSelector."),
        passed=passed,
        metrics={
            "candidates": candidate_count,
            "selected_agent": selection.get("agent_id"),
            "selected_score": round(float(selection.get("score", 0.0)), 4),
            "winner_run_count": ran.count("WriterIdle"),
            "loser_run_count": ran.count("WriterBusy"),
            "elapsed_ms": round(elapsed_ms, 3),
        },
    )


async def check_council_vote_check() -> VeracityCheck:
    registry = AgentRegistry()
    for agent_id, choice in (("v1", "approve"), ("v2", "approve"), ("v3", "reject")):
        registry.register_agent(agent_instance=CouncilVoteAgent(agent_id, choice), goal_type=BenchGoal)
    ship_ran: list[str] = []
    registry.register_agent(
        agent_instance=GateTextAgent("shipper", "shipped", ran=ship_ran),
        goal_type=BenchGoal,
    )
    gate = Node.council(
        id="gate",
        name="ship gate",
        members=("v1", "v2", "v3"),
        options=("approve", "reject"),
        prompt="ship it?",
        output_key="verdict",
    )
    ship = Node.agent(id="ship", name="ship", agent_id="shipper", output_key="ship_out")
    dag = DAG(
        name="bench-council",
        nodes=(gate, ship),
        edges=(
            Edge(
                source=NodeID("gate"),
                target=NodeID("ship"),
                condition=EdgeCondition.JSON_RULE,
                condition_rule=Condition(
                    field="verdict",
                    operator=ConditionOperator.EQUALS,
                    value="approve",
                ),
            ),
        ),
        entry_node=NodeID("gate"),
    )
    executor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_logging=False, enable_events=False),
    )

    start = time.perf_counter()
    result = await executor.run(dag=dag)
    elapsed_ms = (time.perf_counter() - start) * 1000
    gate_result = next((item for item in result.node_results if item.node_id == NodeID("gate")), None)
    ship_result = next((item for item in result.node_results if item.node_id == NodeID("ship")), None)
    council = gate_result.metadata.get("council", {}) if gate_result is not None else {}
    tally = council.get("tally", {})
    ballots = council.get("ballots", ())
    passed = (
        result.success
        and gate_result is not None
        and ship_result is not None
        and gate_result.output == "approve"
        and tally == {"approve": 2.0, "reject": 1.0}
        and len(ballots) == 3
        and ship_ran == ["shipper"]
    )
    return VeracityCheck(
        check_id="council-vote-steers-dag",
        statement=(
            "Council nodes aggregate member votes, preserve ballot metadata, and steer downstream DAG edges."
        ),
        source="README.md: Hard problems table / Council node-kind",
        evidence=("Ran a Node.council DAG with three voters and a JSON_RULE edge opened by the verdict."),
        passed=passed,
        metrics={
            "winning_choice": council.get("winning_choice"),
            "ballots": len(ballots),
            "tally": tally,
            "downstream_runs": ship_ran.count("shipper"),
            "elapsed_ms": round(elapsed_ms, 3),
        },
    )


async def check_gate_interceptor_check() -> VeracityCheck:
    def executor_for(gen: GateTextAgent, ran: list[str]) -> Any:
        registry = AgentRegistry()
        registry.register_agent(agent_instance=gen, goal_type=BenchGoal)
        registry.register_agent(
            agent_instance=GateTextAgent("use", "used", ran=ran),
            goal_type=BenchGoal,
        )
        pipeline = create_interceptor_pipeline(
            interceptors=(
                GateEvalInterceptor(
                    evaluators=(LengthEvaluator(min_length=100),),
                    node_pattern="gen",
                    threshold=0.5,
                ),
            )
        )
        return create_executor(
            agent_registry=registry,
            services=RuntimeServices(interceptor_pipeline=pipeline),
            config=ExecutorConfig(enable_logging=False, enable_events=False),
        )

    fail_ran: list[str] = []
    fail_gen = GateTextAgent("gen", "short")
    fail_executor = executor_for(fail_gen, fail_ran)
    fail_run = await fail_executor.run(dag=_gate_dag(retry=True))
    fail_gen_result = next(item for item in fail_run.node_results if item.node_id == NodeID("gen"))

    pass_ran: list[str] = []
    pass_gen = GateTextAgent("gen", "x" * 200)
    pass_executor = executor_for(pass_gen, pass_ran)
    pass_run = await pass_executor.run(dag=_gate_dag(retry=True))
    pass_gen_result = next(item for item in pass_run.node_results if item.node_id == NodeID("gen"))

    fail_interceptors = fail_gen_result.metadata.get("interceptors", {})
    pass_interceptors = pass_gen_result.metadata.get("interceptors", {})
    passed = (
        not fail_gen_result.success
        and fail_interceptors.get("gate_rejected") is True
        and fail_ran == []
        and fail_gen.runs == 1
        and pass_gen_result.success
        and pass_interceptors.get("gate_eval:gen") == {"gate": "passed", "evaluators": 1}
        and pass_ran == ["use"]
    )
    return VeracityCheck(
        check_id="gate-eval-blocks-downstream",
        statement=(
            "A POST GATE interceptor rejects failing output, blocks downstream "
            "nodes, and does not burn retries."
        ),
        source="README.md: Hard problems table / Citation membership and gate halt",
        evidence=("Ran failing and passing two-node DAGs through GateEvalInterceptor and LengthEvaluator."),
        passed=passed,
        metrics={
            "fail_gate_rejected": fail_interceptors.get("gate_rejected") is True,
            "fail_downstream_runs": len(fail_ran),
            "fail_generator_runs": fail_gen.runs,
            "pass_downstream_runs": len(pass_ran),
            "pass_gate_metadata": pass_interceptors.get("gate_eval:gen"),
        },
    )


def check_citation_tracker_check() -> VeracityCheck:
    tracker = CitationTracker()
    results = [
        SearchResult(
            document=Document(
                id="doc_grounding_1",
                content="CEMAF stores context changes as immutable patches.",
                metadata={"title": "Context Docs", "source_type": "document", "section": "context"},
            ),
            score=0.96,
            rank=1,
            metadata={"retriever": "benchmark"},
        ),
        SearchResult(
            document=Document(
                id="doc_grounding_2",
                content="Each context patch carries source, reason, and correlation metadata.",
                metadata={"title": "Patch Docs", "source_type": "document", "section": "patches"},
            ),
            score=0.91,
            rank=2,
            metadata={"retriever": "benchmark"},
        ),
    ]
    citations = tracker.track_search_results(results)
    cited_fact, patch = tracker.create_cited_fact_patch(
        fact="CEMAF context updates carry immutable patch provenance.",
        citations=citations,
        path="research.findings",
        confidence=0.95,
        verification_status="verified",
        correlation_id="bench-citation",
        agent_id="researcher",
        node_id="grounding",
    )
    context = Context().apply(patch)
    tracker.record_uncited_fact("An unsupported factual statement was intentionally recorded.")
    report = tracker.get_citation_report()
    stored_fact = context.get(f"research.findings.{cited_fact.id}")
    passed = (
        report["total_citations"] == 2
        and report["total_cited_facts"] == 1
        and report["total_uncited_facts"] == 1
        and patch.source == PatchSource.TOOL
        and patch.correlation_id == "bench-citation"
        and isinstance(stored_fact, dict)
        and stored_fact.get("citation_count") == 2
        and stored_fact.get("agent_id") == "researcher"
        and stored_fact.get("node_id") == "grounding"
    )
    return VeracityCheck(
        check_id="citation-tracker-provenance",
        statement=(
            "CitationTracker turns retrieved sources into cited factual statements and provenance patches."
        ),
        source="README.md: Hard problems table / grounded output enforcement",
        evidence=(
            "Tracked two SearchResult sources, created a cited-fact ContextPatch, "
            "and recorded one uncited statement."
        ),
        passed=passed,
        metrics={
            "citations": report["total_citations"],
            "cited_facts": report["total_cited_facts"],
            "uncited_facts": report["total_uncited_facts"],
            "citation_rate": report["citation_rate"],
            "patch_source": patch.source.value,
            "patch_correlation_id": patch.correlation_id,
        },
    )


async def check_blueprint_harvest_check() -> VeracityCheck:
    bus = InMemoryEventBus()
    source = InMemoryWritableBlueprintSource()
    library = BlueprintLibrary()
    engine = create_blueprint_harvester(
        writable_source=source,
        event_bus=bus,
        library=library,
        threshold=0.8,
    )
    try:
        await _publish_blueprint_run(
            bus=bus,
            run_id="bench-blueprint-run",
            node_id="writer",
            goal_text="Write a product launch announcement",
            output="# Launch\nWe shipped a reusable benchmark artifact.",
            score=0.95,
        )
        entries = tuple(source.load())
        hits = library.search(query="product launch announcement", k=3)
        resolved = library.resolve(entry_id=hits[0][0].id) if hits else None
        passed = len(entries) == 1 and len(library) == 1 and bool(hits) and resolved is not None
        return VeracityCheck(
            check_id="blueprint-harvest-search",
            statement=(
                "BlueprintHarvesterEngine distills high-scoring runs into reusable, searchable blueprints."
            ),
            source="README.md: Hard problems table / BlueprintHarvesterEngine",
            evidence=(
                "Published task/eval events through InMemoryEventBus and searched "
                "the harvested BlueprintLibrary."
            ),
            passed=passed,
            metrics={
                "source_entries": len(entries),
                "library_entries": len(library),
                "search_hits": len(hits),
                "top_hit_id": hits[0][0].id if hits else "",
                "top_hit_score": hits[0][1] if hits else 0.0,
                "resolved": resolved is not None,
            },
        )
    finally:
        engine.unsubscribe()


async def check_rlm_concurrency_check() -> VeracityCheck:
    corpus, answers = _build_rlm_corpus()
    subset_ids = tuple(sorted(answers.keys())[:12])
    llm = CorpusLLMClient(answers=answers)
    max_tokens = 2200
    tool = create_rlm_tool(
        llm_client=llm,
        token_estimator=SimpleTokenEstimator(chars_per_token=4.0),
        chunk_size=180,
        max_depth=4,
        max_tokens=max_tokens,
    )

    async def run_one(question_id: str) -> tuple[bool, int, float, str]:
        result = await tool.execute(
            instruction=f"For question {question_id}, return the answer string.",
            content=corpus,
            max_depth=4,
            max_tokens=max_tokens,
            chunk_size=180,
        )
        if not result.success:
            return (False, 0, 0.0, "")
        answer = str(result.data)
        expected = answers[question_id]
        leaks = sum(1 for other_id, token in answers.items() if other_id != question_id and token in answer)
        coverage = float(
            result.metadata.get(
                "coverage_ratio",
                int(result.metadata.get("chunks_examined", 0))
                / max(1, int(result.metadata.get("total_chunks_created", 1))),
            )
        )
        return (
            answer == expected and leaks == 0,
            int(result.metadata.get("llm_calls_made", 0)),
            coverage,
            answer,
        )

    start = time.perf_counter()
    outcomes = await asyncio.gather(*(run_one(question_id) for question_id in subset_ids))
    elapsed_ms = (time.perf_counter() - start) * 1000
    passes = sum(1 for ok, _, _, _ in outcomes if ok)
    mismatches = len(subset_ids) - passes
    total_llm_calls = sum(calls for _, calls, _, _ in outcomes)
    min_coverage = min((coverage for _, _, coverage, _ in outcomes), default=0.0)
    sample_failures = [subset_ids[i] for i, (ok, _, _, _) in enumerate(outcomes) if not ok][:5]
    return VeracityCheck(
        check_id="rlm-concurrent-query-isolation",
        statement=(
            "Concurrent calls through one RLM tool remain query-isolated without cross-answer contamination."
        ),
        source="README.md: Concurrent-Run Contamination + docs/rlm.md parallel chunk processing",
        evidence=("Executed 12 concurrent question lookups against one shared RLM tool and mock LLM client."),
        passed=mismatches == 0 and min_coverage >= 1.0,
        metrics={
            "concurrent_queries": len(subset_ids),
            "mismatches": mismatches,
            "sample_failures": sample_failures,
            "total_llm_calls": total_llm_calls,
            "avg_llm_calls": round(total_llm_calls / len(subset_ids), 2),
            "min_coverage": round(min_coverage, 4),
            "elapsed_ms": round(elapsed_ms, 3),
            "queries_per_sec": round(len(subset_ids) / (elapsed_ms / 1000), 2) if elapsed_ms > 0 else 0.0,
        },
    )


async def check_rlm_check() -> VeracityCheck:
    corpus, answers = _build_rlm_corpus()
    llm = CorpusLLMClient(answers=answers)
    max_tokens = 2200
    reserved_output_tokens = 1000
    available_tokens = max_tokens - reserved_output_tokens
    tool = create_rlm_tool(
        llm_client=llm,
        token_estimator=SimpleTokenEstimator(chars_per_token=4.0),
        chunk_size=180,
        max_depth=4,
        max_tokens=max_tokens,
    )

    start = time.perf_counter()
    correct = 0
    total_chunks = 0
    total_chunks_created = 0
    total_llm_calls = 0
    total_depth = 0
    coverage_values: list[float] = []
    failures: list[str] = []
    wrong_answer_leaks = 0
    for question_id, expected in answers.items():
        result = await tool.execute(
            instruction=f"For question {question_id}, return the answer string.",
            content=corpus,
            max_depth=4,
            max_tokens=max_tokens,
            chunk_size=180,
        )
        answer = str(result.data) if result.success else ""
        leaked_answers = [
            other for other_id, other in answers.items() if other_id != question_id and other in answer
        ]
        wrong_answer_leaks += len(leaked_answers)
        if answer == expected:
            correct += 1
        else:
            failures.append(question_id)
        chunks_examined = int(result.metadata.get("chunks_examined", 0))
        chunks_created = int(result.metadata.get("total_chunks_created", 0))
        total_chunks += chunks_examined
        total_chunks_created += chunks_created
        total_llm_calls += int(result.metadata.get("llm_calls_made", 0))
        total_depth += int(result.metadata.get("depth_reached", 0))
        coverage_values.append(
            float(
                result.metadata.get(
                    "coverage_ratio", chunks_examined / chunks_created if chunks_created else 0.0
                )
            )
        )

    elapsed_ms = (time.perf_counter() - start) * 1000
    questions = len(answers)
    accuracy = correct / questions if questions else 0.0
    avg_llm_calls = total_llm_calls / questions if questions else 0.0
    min_coverage = min(coverage_values) if coverage_values else 0.0
    max_avg_llm_calls = 250.0
    return VeracityCheck(
        check_id="rlm-large-context-querying",
        statement=(
            "RLM can query a document larger than one prompt window by chunking and recursive aggregation."
        ),
        source="docs/rlm.md and README.md: rlm/ recursive context queries",
        evidence=("Queried a deterministic 40-section corpus with decoys for 20 exact ground-truth answers."),
        passed=(
            accuracy == 1.0
            and wrong_answer_leaks == 0
            and available_tokens > 0
            and min_coverage >= 1.0
            and avg_llm_calls <= max_avg_llm_calls
        ),
        metrics={
            "questions": questions,
            "correct": correct,
            "accuracy": round(accuracy, 4),
            "failures": failures,
            "wrong_answer_leaks": wrong_answer_leaks,
            "max_tokens": max_tokens,
            "reserved_output_tokens": reserved_output_tokens,
            "available_context_tokens": available_tokens,
            "elapsed_ms": round(elapsed_ms, 3),
            "avg_ms_per_question": round(elapsed_ms / questions, 3),
            "avg_chunks_examined": round(total_chunks / questions, 2),
            "avg_chunks_created": round(total_chunks_created / questions, 2),
            "min_coverage": round(min_coverage, 4),
            "avg_llm_calls": round(avg_llm_calls, 2),
            "max_avg_llm_calls": max_avg_llm_calls,
            "avg_depth": round(total_depth / questions, 2),
            "total_llm_calls": total_llm_calls,
        },
    )


async def run_veracity_checks() -> list[VeracityCheck]:
    return [
        await check_agent_dag_check(),
        await check_pull_cost_check(),
        await check_context_budget_check(),
        check_context_provenance_check(),
        await check_event_bus_check(),
        await check_concurrency_check(),
        await check_auction_selection_check(),
        await check_council_vote_check(),
        await check_gate_interceptor_check(),
        check_citation_tracker_check(),
        await check_blueprint_harvest_check(),
        await check_rlm_concurrency_check(),
        await check_rlm_check(),
    ]


async def run_benchmarks(scale: int) -> list[BenchmarkResult]:
    results: list[BenchmarkResult] = [
        bench_dag_construction(scale),
        bench_quality_police_scoring(scale),
        bench_context_patch_apply(scale),
        await bench_tool_validated_execute(scale),
        await bench_dag_execution_1_node(scale),
        await bench_dag_execution_5_node_chain(scale),
        await bench_context_compilation(scale),
        await bench_context_compaction(scale),
        await bench_event_bus_pubsub(scale),
        await bench_shared_executor_concurrency(scale),
    ]
    return results


def environment_metadata() -> dict[str, Any]:
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }


def build_report(
    *,
    benchmarks: list[BenchmarkResult],
    checks: list[VeracityCheck],
    scale: int,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project": "cemaf",
        "benchmark_scale": scale,
        "environment": environment_metadata(),
        "summary": {
            "benchmarks": len(benchmarks),
            "veracity_checks": len(checks),
            "veracity_checks_passed": sum(1 for check in checks if check.passed),
            "veracity_checks_failed": sum(1 for check in checks if not check.passed),
        },
        "veracity_checks": [check.to_dict() for check in checks],
        "benchmarks": [result.to_dict() for result in benchmarks],
    }


def render_markdown(report: dict[str, Any]) -> str:
    env = report["environment"]
    lines = [
        "# CEMAF Benchmark Veracity Report",
        "",
        f"- Generated: {env['generated_at']}",
        f"- Python: {env['python']} ({env['implementation']})",
        f"- Platform: {env['platform']}",
        f"- Scale: {report['benchmark_scale']}",
        "",
        "## Veracity Checks",
        "",
        "| Status | Check | Evidence | Key numbers |",
        "|---|---|---|---|",
    ]
    for check in report["veracity_checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        metrics = ", ".join(f"{key}={value}" for key, value in check["metrics"].items())
        lines.append(f"| {status} | `{check['check_id']}` | {check['evidence']} | {metrics} |")

    lines.extend(
        [
            "",
            "## Performance Benchmarks",
            "",
            "| Benchmark | Mean ms | Median ms | P95 ms | Ops/sec | Iterations x reps |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for benchmark in report["benchmarks"]:
        lines.append(
            "| {name} | {mean:.3f} | {median:.3f} | {p95:.3f} | {ops:,.0f} | {iters} x {reps} |".format(
                name=benchmark["name"],
                mean=benchmark["mean_ms"],
                median=benchmark["median_ms"],
                p95=benchmark["p95_ms"],
                ops=benchmark["ops_per_sec"],
                iters=benchmark["iterations"],
                reps=benchmark["repetitions"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def print_report(report: dict[str, Any]) -> None:
    print()
    print("=" * 94)
    print("CEMAF BENCHMARKS AND VERACITY CHECKS")
    print("=" * 94)
    print(
        "Veracity checks: {passed}/{total} passed".format(
            passed=report["summary"]["veracity_checks_passed"],
            total=report["summary"]["veracity_checks"],
        )
    )
    print()
    print("Veracity checks")
    print("-" * 94)
    for check in report["veracity_checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        metrics = ", ".join(f"{key}={value}" for key, value in check["metrics"].items())
        print(f"{status:<5} {check['check_id']:<42} {metrics}")

    print()
    print("Performance")
    print("-" * 94)
    print(f"{'Benchmark':<44} {'Mean':>10} {'P95':>10} {'Ops/sec':>12} {'Iters':>8}")
    print("-" * 94)
    for result in report["benchmarks"]:
        print(
            f"{result['name']:<44} "
            f"{result['mean_ms']:>9.3f}ms "
            f"{result['p95_ms']:>9.3f}ms "
            f"{result['ops_per_sec']:>11,.0f} "
            f"{result['iterations']:>8}"
        )
    print("-" * 94)


def write_report(report: dict[str, Any], *, json_out: Path | None, markdown_out: Path | None) -> None:
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(f"Wrote JSON report: {json_out}")
    if markdown_out is not None:
        markdown_out.parent.mkdir(parents=True, exist_ok=True)
        markdown_out.write_text(render_markdown(report))
        print(f"Wrote Markdown report: {markdown_out}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run CEMAF benchmarks and veracity checks.")
    parser.add_argument(
        "--scale",
        type=int,
        default=1,
        help="Positive multiplier for benchmark iterations.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path for machine-readable benchmark evidence.",
    )
    parser.add_argument(
        "--markdown-out",
        type=Path,
        default=None,
        help="Optional path for a human-readable benchmark report.",
    )
    parser.add_argument(
        "--verbose-logs",
        action="store_true",
        help="Keep CEMAF INFO logs enabled during benchmarks.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if args.scale < 1:
        raise SystemExit("--scale must be >= 1")
    if not args.verbose_logs:
        logging.disable(logging.WARNING)

    checks = await run_veracity_checks()
    benchmarks = await run_benchmarks(scale=args.scale)
    report = build_report(benchmarks=benchmarks, checks=checks, scale=args.scale)
    print_report(report)
    write_report(report, json_out=args.json_out, markdown_out=args.markdown_out)

    failed = [check["check_id"] for check in report["veracity_checks"] if not check["passed"]]
    if failed:
        raise SystemExit(f"Veracity checks failed: {', '.join(failed)}")
    print()
    print("All benchmark veracity checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
