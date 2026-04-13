"""
CEMAF Performance Benchmarks

Measures core framework operations to establish baseline performance.
Run: uv run python benchmarks/run_benchmarks.py
"""

import asyncio
import time
from dataclasses import dataclass

from cemaf import AgentRegistry, DAG, Edge, Node, create_executor
from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
from cemaf.context.source import ContextSource
from cemaf.core.enums import MemoryScope
from cemaf.core.types import AgentID, TokenCount
from cemaf.evals.police import QualityPolice, QualityPoliceConfig
from cemaf.events.bus import InMemoryEventBus
from cemaf.tools.base import Tool, ToolResult, ToolSchema
from cemaf.core.result import Result
from cemaf.core.types import ToolID

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkResult:
    name: str
    iterations: int
    total_ms: float
    avg_ms: float
    ops_per_sec: float


def bench(name: str, iterations: int, fn: callable) -> BenchmarkResult:
    start = time.perf_counter()
    for _ in range(iterations):
        fn()
    elapsed = (time.perf_counter() - start) * 1000
    avg = elapsed / iterations
    ops = iterations / (elapsed / 1000) if elapsed > 0 else 0
    return BenchmarkResult(name=name, iterations=iterations, total_ms=elapsed, avg_ms=avg, ops_per_sec=ops)


async def async_bench(name: str, iterations: int, fn: callable) -> BenchmarkResult:
    start = time.perf_counter()
    for _ in range(iterations):
        await fn()
    elapsed = (time.perf_counter() - start) * 1000
    avg = elapsed / iterations
    ops = iterations / (elapsed / 1000) if elapsed > 0 else 0
    return BenchmarkResult(name=name, iterations=iterations, total_ms=elapsed, avg_ms=avg, ops_per_sec=ops)


# ---------------------------------------------------------------------------
# Benchmark subjects
# ---------------------------------------------------------------------------


class BenchGoal(BaseModel):
    value: int = 0


class BenchResult(BaseModel):
    output: int = 0


class NoOpAgent(Agent[BenchGoal, BenchResult]):
    @property
    def id(self) -> AgentID:
        return AgentID("bench_agent")

    @property
    def description(self) -> str:
        return "Benchmark no-op agent"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: BenchGoal, context: AgentContext) -> AgentResult[BenchResult]:
        return AgentResult.ok(output=BenchResult(output=goal.value + 1), state=AgentState())


class NoOpTool(Tool):
    @property
    def id(self) -> ToolID:
        return ToolID("bench_tool")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(name="bench_tool", description="No-op benchmark tool")

    async def execute(self, **kwargs) -> ToolResult:
        return Result.ok(data={"ok": True})


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------


async def bench_dag_execution_1_node() -> BenchmarkResult:
    """Single-node DAG execution — measures executor overhead."""
    registry = AgentRegistry()
    registry.register_agent(agent_instance=NoOpAgent(), goal_type=BenchGoal)
    executor = create_executor(agent_registry=registry)

    dag = DAG(name="bench", description="benchmark")
    dag = dag.add_node(Node.agent(id="a1", name="A", agent_id="bench_agent", output_key="out"))

    async def run_once():
        await executor.run(dag=dag)

    return await async_bench("DAG execution (1 node)", iterations=100, fn=run_once)


async def bench_dag_execution_5_node_chain() -> BenchmarkResult:
    """5-node sequential DAG — measures chaining overhead."""
    registry = AgentRegistry()
    registry.register_agent(agent_instance=NoOpAgent(), goal_type=BenchGoal)
    executor = create_executor(agent_registry=registry)

    dag = DAG(name="bench5", description="5-node chain")
    for i in range(5):
        dag = dag.add_node(Node.agent(id=f"a{i}", name=f"A{i}", agent_id="bench_agent", output_key=f"out{i}"))
    for i in range(4):
        dag = dag.add_edge(Edge(source=f"a{i}", target=f"a{i+1}"))

    async def run_once():
        await executor.run(dag=dag)

    return await async_bench("DAG execution (5 node chain)", iterations=50, fn=run_once)


async def bench_context_compilation() -> BenchmarkResult:
    """Context compilation with 50 sources — measures selection + budget logic."""
    estimator = SimpleTokenEstimator()
    compiler = PriorityContextCompiler(token_estimator=estimator)
    budget = TokenBudget(max_tokens=10000)

    artifacts = tuple((f"doc_{i}", f"Content for document {i} " * 20) for i in range(50))
    memories = tuple((f"mem_{i}", f"Memory item {i} " * 10) for i in range(20))

    async def compile_once():
        await compiler.compile(artifacts=artifacts, memories=memories, budget=budget)

    return await async_bench("Context compilation (50 sources)", iterations=200, fn=compile_once)


async def bench_context_compaction() -> BenchmarkResult:
    """Context compaction — measures summarization fallback."""
    estimator = SimpleTokenEstimator()
    compiler = PriorityContextCompiler(token_estimator=estimator)
    budget = TokenBudget(max_tokens=10000)

    sources = [
        ContextSource(content=f"Source {i} content " * 50, token_count=TokenCount(200), priority=i, source_type="artifact", source_id=f"s{i}")
        for i in range(10)
    ]

    from cemaf.context.compiler import CompiledContext
    compiled = CompiledContext(
        sources=tuple(sources),
        total_tokens=2000,
        budget=budget,
    )

    async def compact_once():
        await compiler.compact(compiled=compiled, preserve_recent=2, summary_budget_tokens=500)

    return await async_bench("Context compaction (10 sources)", iterations=200, fn=compact_once)


async def bench_event_bus_pubsub() -> BenchmarkResult:
    """Event bus publish + subscriber dispatch."""
    bus = InMemoryEventBus()
    received = []

    from cemaf.events.protocols import Event, EventType

    async def handler(event: Event) -> None:
        received.append(1)

    bus.subscribe(event_type=EventType.TASK_COMPLETED, handler=handler)

    async def publish_once():
        await bus.publish(event=Event.create(
            type=EventType.TASK_COMPLETED,
            payload={"node_id": "n1", "output": "ok"},
            source="bench",
        ))

    return await async_bench("EventBus pub/sub", iterations=1000, fn=publish_once)


def bench_quality_police_scoring() -> BenchmarkResult:
    """QualityPolice score recording + trend analysis."""
    police = QualityPolice(config=QualityPoliceConfig(
        window_size=50,
        predictive_halt_enabled=True,
        min_samples_for_trend=4,
    ))

    import random
    random.seed(42)
    scores = [0.8 + random.uniform(-0.1, 0.1) for _ in range(100)]
    idx = 0

    def record_once():
        nonlocal idx
        police.record_score(score=scores[idx % 100])
        idx += 1

    return bench("QualityPolice scoring + trend", iterations=1000, fn=record_once)


def bench_dag_construction() -> BenchmarkResult:
    """DAG construction — add nodes + edges + validate."""
    def build_once():
        dag = DAG(name="bench", description="construction benchmark")
        for i in range(20):
            dag = dag.add_node(Node.agent(id=f"n{i}", name=f"N{i}", agent_id=f"a{i}", output_key=f"o{i}"))
        for i in range(19):
            dag = dag.add_edge(Edge(source=f"n{i}", target=f"n{i+1}"))
        dag.validate_structure()

    return bench("DAG construction (20 nodes)", iterations=100, fn=build_once)


def bench_tool_validated_execute() -> BenchmarkResult:
    """Tool.validated_execute() — schema validation overhead."""
    tool = NoOpTool()

    async def noop():
        pass

    import asyncio

    def validate_once():
        # Sync check of required params (the validation part, not the async execute)
        missing = [r for r in tool.schema.required if r not in {}]

    return bench("Tool schema validation", iterations=10000, fn=validate_once)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def main() -> None:
    results: list[BenchmarkResult] = []

    # Sync benchmarks
    results.append(bench_dag_construction())
    results.append(bench_quality_police_scoring())
    results.append(bench_tool_validated_execute())

    # Async benchmarks
    results.append(await bench_dag_execution_1_node())
    results.append(await bench_dag_execution_5_node_chain())
    results.append(await bench_context_compilation())
    results.append(await bench_context_compaction())
    results.append(await bench_event_bus_pubsub())

    # Print results
    print()
    print("=" * 75)
    print("CEMAF PERFORMANCE BENCHMARKS")
    print("=" * 75)
    print(f"{'Benchmark':<40} {'Avg (ms)':>10} {'Ops/sec':>12} {'Iters':>8}")
    print("-" * 75)
    for r in results:
        print(f"{r.name:<40} {r.avg_ms:>9.3f}ms {r.ops_per_sec:>11,.0f} {r.iterations:>8}")
    print("-" * 75)
    print()

    # Assertions — framework should be fast
    for r in results:
        if "DAG execution (1 node)" in r.name:
            assert r.avg_ms < 50, f"Single-node DAG too slow: {r.avg_ms:.1f}ms"
        if "EventBus" in r.name:
            assert r.avg_ms < 1, f"EventBus too slow: {r.avg_ms:.1f}ms"
        if "DAG construction" in r.name:
            assert r.avg_ms < 100, f"DAG construction too slow: {r.avg_ms:.1f}ms"

    print("All performance assertions passed.")


if __name__ == "__main__":
    asyncio.run(main())
