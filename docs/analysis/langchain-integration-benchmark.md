# LangChain Integration And Framework-Fit Benchmark

Branch: `drchinca/CMF-XX/benchmarking_langchain`

This benchmark started as a speed comparison, but speed is only a secondary
adoption signal for LLM orchestration. BrightAgent Studio also needs
assertiveness, health checks, recovery, audit logs, traceability,
reproducibility, hallucination controls, insightfulness, and proactivity.

The timing benchmark compares CEMAF against real LangChain/LangGraph framework
paths for offline orchestration scenarios. It is not a mock "LangChain-like"
harness: the benchmark imports `langchain-core` LCEL
`RunnableLambda`/`RunnableParallel` and `langgraph.graph.StateGraph`.

The dependencies remain benchmark-only. Run them through `uv --with` so CEMAF
core stays framework-agnostic:

```bash
uv run --with langchain-core --with langgraph \
  python benchmarks/benchmark_langchain_integration.py \
  --iterations 50 \
  --warmups 5 \
  --steps 8 \
  --branches 8 \
  --doc-size 700 \
  --cpu-rounds 6 \
  --io-delay-ms 2 \
  --output-json docs/analysis/langchain-integration-benchmark-results.json
```

The command emits wall-time statistics plus `cProfile` and `tracemalloc` data.
The JSON artifact includes the top cumulative profiler rows per framework and
scenario: [langchain-integration-benchmark-results.json](langchain-integration-benchmark-results.json).

The adoption-shape PoC is separate and exercises the intended integration
boundary:

```bash
uv run --with langchain-core --with langgraph \
  python examples/app_shapes/cemaf_langgraph_lcel_poc.py
```

That PoC runs a CEMAF DAG with `RuntimeServices(EventBus, RunLogger)`, delegates
one node to a real LangGraph state graph, uses LCEL runnables inside LangGraph,
then replays the CEMAF `RunLogger` patch log to prove reproducibility.

## Scenarios

| Scenario | Meaning |
|---|---|
| `linear` | Eight sequential async state transforms with small deterministic CPU work and I/O delay. |
| `parallel_map_reduce` | Eight document-scoring branches run in parallel, followed by a reduce step. |

## Compared Paths

| Framework path | Implementation |
|---|---|
| CEMAF | `DAGExecutor` with `Node.parallel`, `RuntimeServices`, `EventBus`, `RunLogger`, context patches. |
| LangChain LCEL | Real `RunnableLambda` chains and real `RunnableParallel`. |
| LangGraph | Real `StateGraph` with sequential edges and parallel fan-out into a reducer. |

## Local Result

Environment: Python 3.14.0 on macOS arm64. LangChain emitted its current
Pydantic-v1-on-Python-3.14 compatibility warning during import; the benchmark
keeps that visible because it is real integration evidence.

| Scenario | Framework | Units | Avg | P95 | Peak KiB | cProfile calls | Patches | Events |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| linear | CEMAF | 8 | 21.263ms | 25.921ms | 469.9 | 128,751 | 8.0 | 18.0 |
| linear | LangChain LCEL | 8 | 24.242ms | 31.045ms | 50.8 | 465,551 | 0.0 | 0.0 |
| linear | LangGraph | 8 | 22.789ms | 26.672ms | 119.3 | 435,201 | 0.0 | 0.0 |
| parallel_map_reduce | CEMAF | 8 | 7.834ms | 8.037ms | 437.5 | 1,906,401 | 10.0 | 13.0 |
| parallel_map_reduce | LangChain LCEL | 8 | 5.869ms | 6.142ms | 126.7 | 2,208,701 | 0.0 | 0.0 |
| parallel_map_reduce | LangGraph | 8 | 6.359ms | 6.830ms | 208.9 | 2,181,219 | 0.0 | 0.0 |

## Findings

CEMAF is competitive on the sequential orchestration path while producing
operator evidence that LangChain/LangGraph do not produce in this benchmark:
context patches, run logs, and event stream records.

LangChain LCEL is the fastest parallel map/reduce path in this run. That is
expected: LCEL has a tight runnable-parallel execution path and the benchmark
does not ask it to emit CEMAF-grade run provenance, replay records, event
payloads, budget hooks, eval hooks, or moderation hooks.

LangGraph sits between LCEL and CEMAF on the parallel path. It gives real graph
state orchestration, but CEMAF still owns stronger framework-level operator
surfaces when `RuntimeServices` are wired.

## Non-Speed Adoption Criteria

| Criterion | CEMAF readiness | LangGraph/LCEL role |
|---|---|---|
| Assertiveness | Strong when encoded as eval/gate policy: the DAG can require an explicit decision node and fail non-answers. | Useful inside an adapter for local chain logic, but the adoption gate should live outside the chain. |
| Health | `RuntimeServices.health_monitor` can block a run before execution. | Keep provider-specific health probes in adapters or service implementations. |
| Self-recovery | `AutoHealManager`, retry policy, and interceptor recovery budget belong to the CEMAF execution lifecycle. | LangGraph can do local recovery, but CEMAF should own run-level failure semantics. |
| Audit log | `EventBus`, `RunLogger`, `ContextPatch`, and optional `audit` subscribers provide the canonical audit trail. | Inner LangGraph/LCEL steps should emit adapter metadata into the CEMAF node result. |
| Traceability | Context patches carry source, reason, node id, and correlation id; task/checkpoint events carry run id. | Use LangGraph state as local state, then publish the adapter result into CEMAF context. |
| Reproducibility | `RunRecord` + replay can reconstruct final context from patch history. The PoC verifies patch-only replay. | LangGraph internals need explicit capture if step-level replay is required. |
| Hallucination control | CEMAF has moderation, validation, evals, groundedness, and citation modules. | LCEL/LangGraph can generate or transform, but grounding gates should be wired through CEMAF services. |
| Insightfulness | Best handled as evaluator criteria plus blueprint harvest from successful runs. | Useful for composing prompt/analysis chains inside the adapter. |
| Proactivity | Best handled as explicit next-action outputs, eval checks, and optional improvement/blueprint loops. | Useful for proposing local next actions, not for owning lifecycle policy. |

Conclusion: CEMAF is not "faster LangGraph." Its advantage is being the outer
operating substrate for LLM runs: lifecycle, controls, evidence, replay, and
governance. LangGraph and LCEL remain valuable execution engines inside adapter
nodes.

## Recommendation

Use CEMAF as BrightAgent Studio's orchestration framework when the workflow needs
DAG lifecycle, `RuntimeServices`, `EventBus`, `RunLogger`, replay, budget/eval/
moderation wiring, and CEMAF-native context provenance.

Use LangChain LCEL or LangGraph inside CEMAF adapter nodes, or keep them as
external owners for already-built hot paths where lower orchestration overhead is
more important than CEMAF's operator and governance substrate.

For the revision-aware DeepAgents skills middleware specifically: keep it inside
the Studio/LangGraph adapter until there is a framework-neutral CEMAF
`RevisionedSkillCatalog` protocol worth adding.
