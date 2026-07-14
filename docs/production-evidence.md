# Capability Evidence Ledger

Status: current, reproducible implementation evidence; not an industry-standard claim

Last verified: 2026-07-14

Release-candidate result with LangChain and LangGraph installed: **4,166 passed,
4 skipped**. The four live-provider cases are opt-in and were run separately
rather than treating their default skips as passes.

## What “proven” means here

A capability is listed only when an automated test drives its public execution
path and asserts the resulting behavior. A protocol-only test is not sufficient.
External adapters also require an opt-in live test against the real service.

The maturity labels are deliberately narrow:

- **Automated**: deterministic unit/integration proof runs in the default suite.
- **Destructive**: the test kills/replaces workers or injects competing/stale work.
- **Live boundary**: an opt-in test crossed a real process, provider, or database boundary.
- **Not profile validated**: no multi-day, managed-failover, security/operations-reviewed
  production profile has graduated yet.

## Current capability claims

| Claim CEMAF can make today | Evidence through the public path | Level | Important boundary |
|---|---|---|---|
| Define multi-agent workflows as typed DAGs | `tests/integration/test_dag_execution.py`, `tests/integration/test_agentic_dag.py` | Automated | Type safety does not prove a deployment topology. |
| Run agents, tools, councils, loops, and conditional routes | `tests/integration/test_release_engine_example.py`, `tests/integration/test_agent_council.py`, `tests/unit/test_loop_node.py`, `tests/integration/test_dag_execution.py` | Automated | Application tools retain responsibility for their external effects. |
| Compile relevant context under explicit token budgets | `tests/unit/test_context_compiler.py`, `tests/unit/context/test_compiler_compact.py`, `tests/unit/rlm/test_engine.py` | Automated | Retrieval relevance depends on the configured retriever/model. |
| Track context mutations with provenance | `tests/unit/test_context_patch.py`, `tests/unit/orchestration/test_executor_provenance.py`, `tests/integration/test_context_long_task_trace.py` | Automated | Provenance is complete only for mutations made through CEMAF protocols. |
| Connect custom LLMs, memory stores, and vector stores through protocols | `tests/integration/test_composed_engine.py`, `tests/integration/test_memory_context_bridge.py`, `tests/unit/retrieval/test_vector_store.py` | Automated | A conformant adapter is not automatically operationally mature. |
| Select agents statically or through capability auctions | `tests/integration/test_agent_auction.py` | Automated | Auction quality is bounded by registered capabilities and bid policy. |
| Gate outputs with evaluation, moderation, validation, and citation checks | `tests/integration/test_eval_full_flow.py`, `tests/unit/orchestration/test_executor_moderation.py`, `tests/integration/test_validation_gate.py`, `tests/integration/test_citation_self_healing.py` | Automated | Policy/rule coverage is deployment configuration, not a universal safety guarantee. |
| Apply bounded retries and recovery policies | `tests/unit/interceptors/test_recovery.py`, `tests/integration/test_heal_infinite_loop_prevention.py`, `tests/unit/resilience/test_retry.py` | Automated | Arbitrary non-idempotent effects still need an idempotency key or outbox adapter. |
| Checkpoint and resume file-backed workflows across worker replacement | `tests/integration/test_runtime_services_durable_resume.py`, `tests/integration/test_disposable_workers_durable_companion.py` | Automated + destructive | File authority is a local reference profile, not distributed production authority. |
| Reject stale local workers with leases and fencing tokens | `tests/unit/orchestration/test_run_lease.py`, `tests/integration/test_durable_companion_red_team.py` | Automated + destructive | Fencing is local until a production authority adapter implements atomic fenced commits. |
| Replay recorded context changes deterministically | `tests/unit/test_replay.py`, `tests/integration/test_runtime_services_durable_resume.py` | Automated | Patch replay does not re-run or prove determinism of arbitrary external effects. |
| Trace runs, node attempts, costs, tokens, events, and failures | `tests/integration/test_otel_runtime_trace.py`, `tests/integration/test_composed_engine.py`, `tests/unit/observability/test_token_telemetry.py` | Automated | Export durability/retention belongs to the configured telemetry backend. |
| Maintain scoped semantic and episodic memory | `tests/unit/memory/test_semantic.py`, `tests/unit/memory/test_episodic.py`, `tests/unit/memory/test_scope_hierarchy.py` | Automated | Scope correctness still depends on deployment authorization and tenant isolation. |
| Generate and reuse structured semantic blueprints | `tests/integration/test_blueprint_library.py`, `tests/integration/test_blueprint_harvest_factory.py`, `tests/integration/test_composed_engine.py` | Automated | Harvested blueprints require application-specific review/policy. |
| Process long context through retrieval, compaction, and recursive decomposition | `tests/integration/rlm/test_rlm_large_context.py`, `tests/unit/context/test_compiler_compact.py`, `tests/unit/rlm/test_engine.py` | Automated | This is bounded-behavior proof, not terabyte-scale evidence. |
| Compose these capabilities through one `RuntimeServices` execution root | `tests/integration/test_composed_engine.py`, `tests/integration/test_runtime_services_durable_resume.py`, `tests/integration/test_concurrent_runtime_services_load.py` | Automated + destructive | Optional services must be explicitly injected; no hidden durable boss-agent exists. |

## Real external-boundary checks

These tests skip unless explicitly enabled, so CI cannot turn a missing credential
or daemon into a false green:

```bash
# Local model process (verified with Ollama gemma3:4b)
CEMAF_RUN_LOCAL_LLM_TESTS=1 uv run pytest -q tests/integration/test_ollama_local_live.py

# Real OpenAI and Gemini APIs; requires their provider keys
CEMAF_RUN_CLOUD_LLM_TESTS=1 uv run pytest -q tests/integration/test_cloud_llm_live.py

# Real PostgreSQL server; requires a disposable test database
CEMAF_POSTGRES_DSN=postgresql://... uv run pytest -q tests/integration/test_postgres_memory_store.py
```

The 2026-07-14 verification produced 2/2 Ollama tests, 2/2 cloud-provider
tests, and 6/6 PostgreSQL tests. Credentials and response bodies are not stored
in the repository.

## Destructive and load checks

```bash
uv run pytest -q \
  tests/integration/test_disposable_workers_durable_companion.py \
  tests/integration/test_durable_companion_red_team.py \
  tests/integration/test_runtime_services_durable_resume.py \
  tests/integration/test_concurrent_runtime_services_load.py

uv run python benchmarks/stress_disposable_workers.py --runs 300
uv run python benchmarks/red_team_durable_companion.py
```

The 300-pipeline run killed and replaced every worker, healed and replayed every
run, preserved 1,200 unique patches, and committed one idempotent effect per
pipeline at 86.32 pipelines/second. The red-team harness also survived SIGKILL,
duplicate resumers, and interrupted checkpoint, trace, and effect writes with
no broken invariants. That is useful local destructive evidence, not evidence
of managed backend failover or multi-day operation.

## Claims still prohibited

CEMAF must not currently claim industry-standard maturity, exactly-once behavior
for arbitrary external APIs, managed backend failover, multi-day survival, or
terabyte-scale proof. Graduation criteria live in
[Industry-Standard Goals](architecture/industry-standard-goals.md).
