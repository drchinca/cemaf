"""Profile real CEMAF vs LangChain/LangGraph orchestration scenarios.

This benchmark intentionally uses real `langchain-core` and `langgraph` objects
while keeping them out of CEMAF's package dependencies. Run it with ephemeral
benchmark-only dependencies:

    uv run --with langchain-core --with langgraph \
        python benchmarks/benchmark_langchain_integration.py

The scenarios are deterministic offline stand-ins for common agent workflows:
linear state transformation and parallel document map/reduce. They measure wall
time, cProfile call stacks, and tracemalloc peak memory for each framework path.
"""

from __future__ import annotations

import argparse
import asyncio
import cProfile
import io
import json
import logging
import operator
import platform
import pstats
import statistics
import sys
import time
import tracemalloc
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated, Any, TypedDict

try:
    from langchain_core.runnables import RunnableLambda, RunnableParallel
    from langgraph.graph import END, START, StateGraph
except ImportError as exc:  # pragma: no cover - exercised by manual invocation
    raise SystemExit(
        "This benchmark uses real LangChain/LangGraph packages. Run:\n"
        "  uv run --with langchain-core --with langgraph "
        "python benchmarks/benchmark_langchain_integration.py"
    ) from exc

from cemaf.context.context import Context
from cemaf.core.enums import NodeType, RunStatus
from cemaf.core.types import JSON, NodeID, RunID
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event
from cemaf.observability.run_logger import InMemoryRunLogger
from cemaf.orchestration.dag import DAG, Edge, Node
from cemaf.orchestration.executor import DAGExecutor
from cemaf.orchestration.results import NodeResult
from cemaf.orchestration.services import RuntimeServices


class LinearState(TypedDict):
    value: int


class MapReduceState(TypedDict):
    docs: list[str]
    scores: Annotated[list[int], operator.add]
    total: int


@dataclass(frozen=True)
class WorkloadConfig:
    iterations: int
    warmups: int
    steps: int
    branches: int
    doc_size: int
    cpu_rounds: int
    io_delay_ms: float


@dataclass(frozen=True)
class RunOutcome:
    final_value: int
    patches: int
    events: int


@dataclass(frozen=True)
class ProfileResult:
    framework: str
    scenario: str
    iterations: int
    units: int
    avg_ms: float
    p50_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float
    ops_per_sec: float
    profile_wall_ms: float
    profile_calls: int
    peak_kib: float
    avg_patches: float
    avg_events: float
    final_value: int
    profile_top: tuple[str, ...]


class ScenarioNodeExecutor:
    """CEMAF NodeExecutor for deterministic offline benchmark nodes."""

    def __init__(self, *, docs: tuple[str, ...], cpu_rounds: int, io_delay_ms: float) -> None:
        self._docs = docs
        self._cpu_rounds = cpu_rounds
        self._io_delay_seconds = io_delay_ms / 1000

    async def execute_node(self, node: Node, context: Context) -> NodeResult:
        start = time.perf_counter()
        try:
            output = await self._run_node(node=node, context=context)
        except Exception as exc:  # noqa: BLE001 - node executors contain adapter failures
            return NodeResult(
                node_id=node.id,
                success=False,
                error=str(exc),
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        return NodeResult(
            node_id=node.id,
            success=True,
            output=output,
            duration_ms=(time.perf_counter() - start) * 1000,
        )

    async def _run_node(self, *, node: Node, context: Context) -> int:
        role = str((node.config or {}).get("role", ""))
        if self._io_delay_seconds > 0:
            await asyncio.sleep(self._io_delay_seconds)

        if role == "linear_step":
            inputs = context.get("_resolved_inputs", default={})
            value = int(inputs.get("value", context.get("value", default=0)))
            return transform_value(
                value=value,
                step=int((node.config or {}).get("step", 0)),
                rounds=self._cpu_rounds,
            )

        if role == "score_doc":
            index = int((node.config or {}).get("index", 0))
            return score_doc(self._docs[index], rounds=self._cpu_rounds)

        if role == "reduce_scores":
            inputs = context.get("_resolved_inputs", default={})
            scores = inputs.get("scores", {})
            if isinstance(scores, dict):
                return sum(int(value) for value in scores.values())
            if isinstance(scores, list):
                return sum(int(value) for value in scores)
            return 0

        raise ValueError(f"unknown benchmark node role: {role!r}")


def transform_value(*, value: int, step: int, rounds: int) -> int:
    acc = value + step + 1
    for idx in range(rounds):
        acc = ((acc * 33) ^ (idx + step)) & 0xFFFFFFFF
    return acc


def score_doc(text: str, *, rounds: int) -> int:
    total = 0
    for round_index in range(rounds):
        for char in text:
            total = (total + ((ord(char) + round_index) % 97)) & 0xFFFFFFFF
    return total % 100_000


def make_docs(*, branches: int, doc_size: int) -> tuple[str, ...]:
    base = (
        "BrightAgent Studio evaluates orchestration, state, skills, replay, "
        "parallel branches, and operator evidence. "
    )
    return tuple((base + f"document-{idx} ") * max(1, doc_size // len(base)) for idx in range(branches))


def node_with_config(
    *,
    id: str,
    name: str,
    config: JSON,
    input_mapping: JSON | None = None,
    output_key: str = "",
) -> Node:
    return Node(
        id=NodeID(id),
        type=NodeType.TOOL,
        name=name,
        ref_id=name,
        config=config,
        input_mapping=input_mapping or {},
        output_key=output_key,
        retry_on_failure=False,
    )


def build_cemaf_linear(*, steps: int) -> DAG:
    dag = DAG(name="cemaf_linear_profile", description="Sequential state transform")
    for step in range(steps):
        node_id = f"step_{step}"
        dag = dag.add_node(
            node_with_config(
                id=node_id,
                name=node_id,
                config={"role": "linear_step", "step": step},
                input_mapping={"value": "$$value$$"},
                output_key="value",
            )
        )
        if step > 0:
            dag = dag.add_edge(Edge(source=NodeID(f"step_{step - 1}"), target=NodeID(node_id)))
    return dag


def build_cemaf_parallel(*, branches: int) -> DAG:
    dag = DAG(name="cemaf_parallel_profile", description="Parallel document map/reduce")
    branch_ids = [f"score_{idx}" for idx in range(branches)]
    dag = dag.add_node(
        Node.parallel(
            id="fanout",
            name="Fanout",
            parallel_nodes=branch_ids,
            output_key="scores",
        )
    )
    dag = dag.add_node(
        node_with_config(
            id="reduce",
            name="reduce",
            config={"role": "reduce_scores"},
            input_mapping={"scores": "$$scores$$"},
            output_key="total",
        )
    )
    for idx, branch_id in enumerate(branch_ids):
        dag = dag.add_node(
            node_with_config(
                id=branch_id,
                name=branch_id,
                config={"role": "score_doc", "index": idx},
                output_key=f"score_{idx}",
            )
        )
        dag = dag.add_edge(Edge(source=NodeID("fanout"), target=NodeID(branch_id)))
        dag = dag.add_edge(Edge(source=NodeID(branch_id), target=NodeID("reduce")))
    return dag


def build_langchain_linear(*, steps: int, cpu_rounds: int, io_delay_ms: float) -> Any:
    async def identity(state: LinearState) -> LinearState:
        return state

    chain: Any = RunnableLambda(identity)
    for step in range(steps):
        chain = chain | RunnableLambda(
            make_langchain_linear_step(
                step=step,
                cpu_rounds=cpu_rounds,
                io_delay_ms=io_delay_ms,
            )
        )
    return chain


def make_langchain_linear_step(
    *, step: int, cpu_rounds: int, io_delay_ms: float
) -> Callable[[LinearState], Awaitable[LinearState]]:
    async def run(state: LinearState) -> LinearState:
        if io_delay_ms > 0:
            await asyncio.sleep(io_delay_ms / 1000)
        return {"value": transform_value(value=int(state["value"]), step=step, rounds=cpu_rounds)}

    return run


def build_langchain_parallel(*, docs: tuple[str, ...], cpu_rounds: int, io_delay_ms: float) -> Any:
    branches = {
        f"score_{idx}": RunnableLambda(
            make_langchain_score_doc(index=idx, docs=docs, cpu_rounds=cpu_rounds, io_delay_ms=io_delay_ms)
        )
        for idx in range(len(docs))
    }

    async def reduce(scores: dict[str, int]) -> dict[str, int]:
        return {"total": sum(scores.values())}

    return RunnableParallel(branches) | RunnableLambda(reduce)


def make_langchain_score_doc(
    *, index: int, docs: tuple[str, ...], cpu_rounds: int, io_delay_ms: float
) -> Callable[[dict[str, Any]], Awaitable[int]]:
    async def run(state: dict[str, Any]) -> int:
        del state
        if io_delay_ms > 0:
            await asyncio.sleep(io_delay_ms / 1000)
        return score_doc(docs[index], rounds=cpu_rounds)

    return run


def build_langgraph_linear(*, steps: int, cpu_rounds: int, io_delay_ms: float) -> Any:
    graph = StateGraph(LinearState)
    previous = START
    for step in range(steps):
        node_name = f"step_{step}"
        graph.add_node(
            node_name,
            make_langgraph_linear_step(
                step=step,
                cpu_rounds=cpu_rounds,
                io_delay_ms=io_delay_ms,
            ),
        )
        graph.add_edge(previous, node_name)
        previous = node_name
    graph.add_edge(previous, END)
    return graph.compile()


def make_langgraph_linear_step(
    *, step: int, cpu_rounds: int, io_delay_ms: float
) -> Callable[[LinearState], Awaitable[LinearState]]:
    async def run(state: LinearState) -> LinearState:
        if io_delay_ms > 0:
            await asyncio.sleep(io_delay_ms / 1000)
        return {"value": transform_value(value=int(state["value"]), step=step, rounds=cpu_rounds)}

    return run


def build_langgraph_parallel(*, docs: tuple[str, ...], cpu_rounds: int, io_delay_ms: float) -> Any:
    graph = StateGraph(MapReduceState)
    for idx in range(len(docs)):
        node_name = f"score_{idx}"
        graph.add_node(
            node_name,
            make_langgraph_score_doc(index=idx, docs=docs, cpu_rounds=cpu_rounds, io_delay_ms=io_delay_ms),
        )
        graph.add_edge(START, node_name)
        graph.add_edge(node_name, "reduce")
    graph.add_node("reduce", langgraph_reduce_scores)
    graph.add_edge("reduce", END)
    return graph.compile()


def make_langgraph_score_doc(
    *, index: int, docs: tuple[str, ...], cpu_rounds: int, io_delay_ms: float
) -> Callable[[MapReduceState], Awaitable[MapReduceState]]:
    async def run(state: MapReduceState) -> MapReduceState:
        del state
        if io_delay_ms > 0:
            await asyncio.sleep(io_delay_ms / 1000)
        return {"scores": [score_doc(docs[index], rounds=cpu_rounds)]}

    return run


async def langgraph_reduce_scores(state: MapReduceState) -> MapReduceState:
    return {"total": sum(state.get("scores", []))}


def make_cemaf_runner(
    *,
    scenario: str,
    config: WorkloadConfig,
    docs: tuple[str, ...],
) -> Callable[[], Awaitable[RunOutcome]]:
    logger = InMemoryRunLogger()
    bus = InMemoryEventBus()
    event_count = 0
    node_executor = ScenarioNodeExecutor(
        docs=docs,
        cpu_rounds=config.cpu_rounds,
        io_delay_ms=config.io_delay_ms,
    )
    executor = DAGExecutor(
        node_executor=node_executor,
        services=RuntimeServices(run_logger=logger, event_bus=bus),
    )
    dag = (
        build_cemaf_linear(steps=config.steps)
        if scenario == "linear"
        else build_cemaf_parallel(branches=config.branches)
    )
    run_counter = 0

    async def count_event(event: Event) -> None:
        nonlocal event_count
        event_count += 1

    bus.subscribe_all(count_event)

    async def run_once() -> RunOutcome:
        nonlocal run_counter
        run_id = f"cemaf_{scenario}_{run_counter}"
        run_counter += 1
        before_events = event_count
        initial = (
            Context(data={"value": 1})
            if scenario == "linear"
            else Context(data={"docs": list(docs), "scores": {}, "total": 0})
        )
        result = await executor.run(dag=dag, initial_context=initial, run_id=RunID(run_id))
        if result.status is not RunStatus.COMPLETED:
            raise RuntimeError(result.error or f"CEMAF {scenario} run failed")
        record = logger.get_record(run_id)
        final_value = int(result.final_context.get("value" if scenario == "linear" else "total", default=0))
        return RunOutcome(
            final_value=final_value,
            patches=record.total_patches if record is not None else 0,
            events=event_count - before_events,
        )

    return run_once


def make_langchain_runner(
    *,
    scenario: str,
    config: WorkloadConfig,
    docs: tuple[str, ...],
) -> Callable[[], Awaitable[RunOutcome]]:
    runnable = (
        build_langchain_linear(
            steps=config.steps,
            cpu_rounds=config.cpu_rounds,
            io_delay_ms=config.io_delay_ms,
        )
        if scenario == "linear"
        else build_langchain_parallel(docs=docs, cpu_rounds=config.cpu_rounds, io_delay_ms=config.io_delay_ms)
    )

    async def run_once() -> RunOutcome:
        initial: dict[str, Any] = {"value": 1} if scenario == "linear" else {"docs": list(docs)}
        result = await runnable.ainvoke(initial)
        return RunOutcome(
            final_value=int(result["value" if scenario == "linear" else "total"]),
            patches=0,
            events=0,
        )

    return run_once


def make_langgraph_runner(
    *,
    scenario: str,
    config: WorkloadConfig,
    docs: tuple[str, ...],
) -> Callable[[], Awaitable[RunOutcome]]:
    graph = (
        build_langgraph_linear(
            steps=config.steps,
            cpu_rounds=config.cpu_rounds,
            io_delay_ms=config.io_delay_ms,
        )
        if scenario == "linear"
        else build_langgraph_parallel(docs=docs, cpu_rounds=config.cpu_rounds, io_delay_ms=config.io_delay_ms)
    )

    async def run_once() -> RunOutcome:
        initial: dict[str, Any] = (
            {"value": 1} if scenario == "linear" else {"docs": list(docs), "scores": [], "total": 0}
        )
        result = await graph.ainvoke(initial)
        return RunOutcome(
            final_value=int(result["value" if scenario == "linear" else "total"]),
            patches=0,
            events=0,
        )

    return run_once


async def measure(
    *,
    framework: str,
    scenario: str,
    units: int,
    config: WorkloadConfig,
    run_once: Callable[[], Awaitable[RunOutcome]],
) -> ProfileResult:
    for _ in range(config.warmups):
        await run_once()

    timings: list[float] = []
    outcomes: list[RunOutcome] = []
    for _ in range(config.iterations):
        start = time.perf_counter()
        outcomes.append(await run_once())
        timings.append((time.perf_counter() - start) * 1000)

    profiler = cProfile.Profile()
    tracemalloc.start()
    profile_start = time.perf_counter()
    profiler.enable()
    for _ in range(config.iterations):
        await run_once()
    profiler.disable()
    profile_wall_ms = (time.perf_counter() - profile_start) * 1000
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    profile_top = format_profile_top(profiler=profiler)
    profile_calls = pstats.Stats(profiler, stream=io.StringIO()).total_calls
    ordered = sorted(timings)
    p95_index = min(len(ordered) - 1, int(len(ordered) * 0.95))
    avg_ms = statistics.fmean(timings)
    return ProfileResult(
        framework=framework,
        scenario=scenario,
        iterations=config.iterations,
        units=units,
        avg_ms=avg_ms,
        p50_ms=statistics.median(timings),
        p95_ms=ordered[p95_index],
        min_ms=min(timings),
        max_ms=max(timings),
        ops_per_sec=1000 / avg_ms if avg_ms > 0 else 0,
        profile_wall_ms=profile_wall_ms,
        profile_calls=profile_calls,
        peak_kib=peak / 1024,
        avg_patches=statistics.fmean(outcome.patches for outcome in outcomes),
        avg_events=statistics.fmean(outcome.events for outcome in outcomes),
        final_value=outcomes[-1].final_value,
        profile_top=profile_top,
    )


def format_profile_top(*, profiler: cProfile.Profile, limit: int = 10) -> tuple[str, ...]:
    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("cumtime")
    stats.print_stats(limit)
    lines = [line.rstrip() for line in stream.getvalue().splitlines()]
    return tuple(line for line in lines if line.strip())[-limit:]


async def run_suite(config: WorkloadConfig) -> list[ProfileResult]:
    docs = make_docs(branches=config.branches, doc_size=config.doc_size)
    suite: list[ProfileResult] = []
    for scenario, units in (("linear", config.steps), ("parallel_map_reduce", config.branches)):
        suite.append(
            await measure(
                framework="CEMAF",
                scenario=scenario,
                units=units,
                config=config,
                run_once=make_cemaf_runner(
                    scenario="linear" if scenario == "linear" else "parallel",
                    config=config,
                    docs=docs,
                ),
            )
        )
        suite.append(
            await measure(
                framework="LangChain LCEL",
                scenario=scenario,
                units=units,
                config=config,
                run_once=make_langchain_runner(
                    scenario="linear" if scenario == "linear" else "parallel",
                    config=config,
                    docs=docs,
                ),
            )
        )
        suite.append(
            await measure(
                framework="LangGraph",
                scenario=scenario,
                units=units,
                config=config,
                run_once=make_langgraph_runner(
                    scenario="linear" if scenario == "linear" else "parallel",
                    config=config,
                    docs=docs,
                ),
            )
        )
    return suite


def print_results(results: list[ProfileResult]) -> None:
    print()
    print("=" * 132)
    print("CEMAF vs LANGCHAIN/LANGGRAPH REAL-FRAMEWORK PROFILER BENCHMARK")
    print("=" * 132)
    print(
        f"{'Scenario':<22} {'Framework':<16} {'Units':>5} {'Avg':>10} {'P95':>10} "
        f"{'Ops/s':>10} {'Peak KiB':>10} {'Calls':>10} {'Patches':>8} {'Events':>8} {'Final':>10}"
    )
    print("-" * 132)
    for result in results:
        print(
            f"{result.scenario:<22} {result.framework:<16} {result.units:>5} "
            f"{result.avg_ms:>9.3f}ms {result.p95_ms:>9.3f}ms {result.ops_per_sec:>10,.0f} "
            f"{result.peak_kib:>10,.1f} {result.profile_calls:>10,} "
            f"{result.avg_patches:>8.1f} {result.avg_events:>8.1f} {result.final_value:>10}"
        )
    print("-" * 132)
    print()


def recommendation(results: list[ProfileResult]) -> str:
    by_key = {(result.framework, result.scenario): result for result in results}
    cemaf_parallel = by_key[("CEMAF", "parallel_map_reduce")]
    langgraph_parallel = by_key[("LangGraph", "parallel_map_reduce")]
    lcel_parallel = by_key[("LangChain LCEL", "parallel_map_reduce")]
    fastest_parallel = min((cemaf_parallel, langgraph_parallel, lcel_parallel), key=lambda item: item.avg_ms)

    return (
        f"Fastest parallel map/reduce path in this run: {fastest_parallel.framework} "
        f"({fastest_parallel.avg_ms:.3f}ms avg). Use CEMAF as the orchestration framework when "
        "the product needs DAG lifecycle, RuntimeServices, EventBus, RunLogger, replay, "
        "budget/eval/moderation wiring, and CEMAF-native context provenance. Use LangGraph/LCEL "
        "inside adapter nodes or for already-built flows where their lower orchestration overhead "
        "matters more than CEMAF's operator and governance substrate."
    )


def result_payload(*, config: WorkloadConfig, results: list[ProfileResult]) -> dict[str, Any]:
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "config": asdict(config),
        "results": [
            {
                **asdict(result),
                "profile_top": list(result.profile_top),
            }
            for result in results
        ],
        "recommendation": recommendation(results),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--branches", type=int, default=8)
    parser.add_argument("--doc-size", type=int, default=700)
    parser.add_argument("--cpu-rounds", type=int, default=6)
    parser.add_argument("--io-delay-ms", type=float, default=2.0)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not args.verbose:
        logging.getLogger("cemaf").setLevel(logging.WARNING)

    config = WorkloadConfig(
        iterations=args.iterations,
        warmups=args.warmups,
        steps=args.steps,
        branches=args.branches,
        doc_size=args.doc_size,
        cpu_rounds=args.cpu_rounds,
        io_delay_ms=args.io_delay_ms,
    )
    results = await run_suite(config)
    print_results(results)
    print(recommendation(results))
    print()

    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(result_payload(config=config, results=results), indent=2) + "\n"
        )
        print(f"Wrote profiler artifact: {args.output_json}")


if __name__ == "__main__":
    asyncio.run(main())
