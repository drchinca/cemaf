# CEMAF Benchmark Veracity Report

- Generated: 2026-06-23T03:48:14.753303+00:00
- Python: 3.14.0 (CPython)
- Platform: macOS-26.2-arm64-arm-64bit-Mach-O
- Scale: 1

## Veracity Checks

| Status | Check | Evidence | Key numbers |
|---|---|---|---|
| PASS | `agent-dag-units-of-work` | Ran one registered Agent through create_executor() 25 times with distinct inputs. | runs=25, successes=25, elapsed_ms=1.661, avg_ms=0.066 |
| PASS | `pull-cost-absent-services-do-not-run` | Injected a CountingLLMClient into RuntimeServices and executed 25 no-op agent DAG runs. | runs=25, llm_calls=0, elapsed_ms=1.031, avg_ms=0.041 |
| PASS | `context-budget-selection` | Compiled 30 oversized artifacts into a 400-token available budget. | input_sources=30, selected_sources=1, available_tokens=400, compiled_tokens=315, within_budget=True, selected_keys=['doc_0'] |
| PASS | `context-patch-provenance` | Applied tool and agent patches, inspected timeline, and rolled back to a prior patch ID. | patches=3, final_hash=3d4c02a43595b0d1, rollback_hash=39e1712d9ba1734f, sources=['tool', 'agent', 'tool'] |
| PASS | `typed-event-stream` | Published 100 TASK_COMPLETED events through InMemoryEventBus.publish_batch(). | published=100, received=100, elapsed_ms=0.041, events_per_sec=2409638.8 |
| PASS | `shared-executor-concurrency-isolation` | Ran 64 concurrent calls through one executor with distinct initial context values. | runs=64, mismatches=0, elapsed_ms=3.245, runs_per_sec=19722.9 |
| PASS | `rlm-large-context-querying` | Queried a deterministic 40-section corpus for 20 ground-truth answers via create_rlm_tool(). | questions=20, correct=20, accuracy=1.0, failures=[], elapsed_ms=79.996, avg_ms_per_question=4.0, avg_chunks_examined=120.0, avg_llm_calls=151.0, avg_depth=4.0, total_llm_calls=3020 |

## Performance Benchmarks

| Benchmark | Mean ms | Median ms | P95 ms | Ops/sec | Iterations x reps |
|---|---:|---:|---:|---:|---:|
| DAG construction (20 nodes) | 0.117 | 0.117 | 0.117 | 8,559 | 300 x 5 |
| QualityPolice scoring + trend | 0.015 | 0.015 | 0.016 | 65,162 | 2000 x 5 |
| Context patch apply + provenance | 0.006 | 0.007 | 0.007 | 154,104 | 2000 x 5 |
| Tool validated_execute() | 0.003 | 0.003 | 0.003 | 308,506 | 2000 x 5 |
| DAG execution (1 agent node) | 0.041 | 0.041 | 0.043 | 24,381 | 100 x 5 |
| DAG execution (5 agent chain) | 0.164 | 0.167 | 0.169 | 6,085 | 50 x 5 |
| Context compilation (70 sources) | 0.092 | 0.092 | 0.093 | 10,925 | 200 x 5 |
| Context compaction (10 sources) | 0.005 | 0.004 | 0.005 | 220,163 | 200 x 5 |
| EventBus pub/sub | 0.004 | 0.004 | 0.004 | 247,232 | 1000 x 5 |
| Shared executor concurrent batch (32 runs) | 1.510 | 1.510 | 1.543 | 662 | 5 x 3 |
