# CEMAF Benchmark Veracity Report

- Generated: 2026-06-23T04:06:56.359493+00:00
- Python: 3.14.0 (CPython)
- Platform: macOS-26.2-arm64-arm-64bit-Mach-O
- Scale: 1

## Veracity Checks

| Status | Check | Evidence | Key numbers |
|---|---|---|---|
| PASS | `agent-dag-units-of-work` | Ran one registered Agent through create_executor() 25 times with distinct inputs. | runs=25, successes=25, elapsed_ms=2.035, avg_ms=0.081 |
| PASS | `pull-cost-absent-services-do-not-run` | Injected a CountingLLMClient into RuntimeServices and executed 25 no-op agent DAG runs. | runs=25, llm_calls=0, elapsed_ms=1.115, avg_ms=0.045 |
| PASS | `context-budget-selection` | Compiled 30 oversized artifacts into a 400-token available budget. | input_sources=30, selected_sources=1, available_tokens=400, compiled_tokens=315, within_budget=True, selected_keys=['doc_0'] |
| PASS | `context-patch-provenance` | Applied tool and agent patches, inspected timeline, and rolled back to a prior patch ID. | patches=3, final_hash=a8ec272e757b49bd, rollback_hash=a9fa9fb1b79428bd, sources=['tool', 'agent', 'tool'] |
| PASS | `typed-event-stream` | Published 100 TASK_COMPLETED events through InMemoryEventBus.publish_batch(). | published=100, received=100, elapsed_ms=0.047, events_per_sec=2125759.7 |
| PASS | `shared-executor-concurrency-isolation` | Ran 64 concurrent router DAG calls through one executor with explicit run IDs and EventBus capture. | runs=64, mismatches=0, captured_events=320, wrong_correlation_events=0, missing_dag_completed_events=0, elapsed_ms=6.491, runs_per_sec=9859.8 |
| PASS | `auction-selects-low-load-agent` | Ran a Node.auction DAG with two WRITE-capable agents and a wired DefaultAgentSelector. | candidates=2, selected_agent=WriterIdle, selected_score=0.97, winner_run_count=1, loser_run_count=0, elapsed_ms=0.13 |
| PASS | `council-vote-steers-dag` | Ran a Node.council DAG with three voters and a JSON_RULE edge opened by the verdict. | winning_choice=approve, ballots=3, tally={'approve': 2.0, 'reject': 1.0}, downstream_runs=1, elapsed_ms=0.248 |
| PASS | `gate-eval-blocks-downstream` | Ran failing and passing two-node DAGs through GateEvalInterceptor and LengthEvaluator. | fail_gate_rejected=True, fail_downstream_runs=0, fail_generator_runs=1, pass_downstream_runs=1, pass_gate_metadata={'gate': 'passed', 'evaluators': 1} |
| PASS | `citation-tracker-provenance` | Tracked two SearchResult sources, created a cited-fact ContextPatch, and recorded one uncited statement. | citations=2, cited_facts=1, uncited_facts=1, citation_rate=0.5, patch_source=tool, patch_correlation_id=bench-citation |
| PASS | `blueprint-harvest-search` | Published task/eval events through InMemoryEventBus and searched the harvested BlueprintLibrary. | source_entries=1, library_entries=1, search_hits=1, top_hit_id=harvest/a9c51c7d4b55, top_hit_score=9.0, resolved=True |
| PASS | `rlm-concurrent-query-isolation` | Executed 12 concurrent question lookups against one shared RLM tool and mock LLM client. | concurrent_queries=12, mismatches=0, sample_failures=[], total_llm_calls=12, avg_llm_calls=1.0, min_coverage=1.0, elapsed_ms=29.276, queries_per_sec=409.89 |
| PASS | `rlm-large-context-querying` | Queried a deterministic 40-section corpus with decoys for 20 exact ground-truth answers. | questions=20, correct=20, accuracy=1.0, failures=[], wrong_answer_leaks=0, max_tokens=2200, reserved_output_tokens=1000, available_context_tokens=1200, elapsed_ms=47.501, avg_ms_per_question=2.375, avg_chunks_examined=120.0, avg_chunks_created=120.0, min_coverage=1.0, avg_llm_calls=1.0, max_avg_llm_calls=250.0, avg_depth=0.0, total_llm_calls=20 |

## Performance Benchmarks

| Benchmark | Mean ms | Median ms | P95 ms | Ops/sec | Iterations x reps |
|---|---:|---:|---:|---:|---:|
| DAG construction (20 nodes) | 0.118 | 0.118 | 0.119 | 8,461 | 300 x 5 |
| QualityPolice scoring + trend | 0.016 | 0.016 | 0.016 | 63,984 | 2000 x 5 |
| Context patch apply + provenance | 0.007 | 0.007 | 0.007 | 149,954 | 2000 x 5 |
| Tool validated_execute() | 0.003 | 0.003 | 0.004 | 287,310 | 2000 x 5 |
| DAG execution (1 agent node) | 0.041 | 0.041 | 0.043 | 24,217 | 100 x 5 |
| DAG execution (5 agent chain) | 0.164 | 0.163 | 0.170 | 6,083 | 50 x 5 |
| Context compilation (70 sources) | 0.095 | 0.095 | 0.096 | 10,538 | 200 x 5 |
| Context compaction (10 sources) | 0.005 | 0.005 | 0.005 | 213,203 | 200 x 5 |
| EventBus pub/sub | 0.004 | 0.004 | 0.004 | 241,751 | 1000 x 5 |
| Shared executor concurrent batch (32 runs) | 1.575 | 1.565 | 1.650 | 635 | 5 x 3 |
