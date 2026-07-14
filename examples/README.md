# CEMAF Examples

Runnable proof that CEMAF does what it preaches. Every `.py` here runs offline
(no API key) and is guarded by `tests/integration/test_examples_smoke.py` — if
it's listed, `uv run python examples/<it>.py` works.

## Start here

| Example | Proves |
|---|---|
| [`hello_world.py`](hello_world.py) | Define an agent, build a DAG, run it — the smallest real loop. |

## Bring your own X (the protocol is the only contract)

CEMAF integration points are `@runtime_checkable` protocols. Implement one and
wire it through a factory — never fork the framework.

| Example | Proves |
|---|---|
| [`byo/byo_llm.py`](byo/byo_llm.py) | Drive your own LLM gateway behind the `LLMClient` protocol. |
| [`byo/byo_vector_store.py`](byo/byo_vector_store.py) | CEMAF retrieval over your own store (dict/SQLite), reusing `cosine_similarity`. |
| [`byo/byo_memory.py`](byo/byo_memory.py) | Durable agent memory on SQLite via the `MemoryStore` ABC + `create_memory_manager`. |

## App shapes (what you actually build)

Minimal product slices, not feature tours.

| Example | Proves |
|---|---|
| [`app_shapes/rag_with_citations.py`](app_shapes/rag_with_citations.py) | Grounded RAG — every answer traces to a retrieved source (the membership invariant). |
| [`app_shapes/tool_using_agent.py`](app_shapes/tool_using_agent.py) | An agent calls a flaky tool that self-heals via `@with_retry`, all inside a DAG. |
| [`app_shapes/disposable_workers_durable_companion.py`](app_shapes/disposable_workers_durable_companion.py) | Two or three disposable workers die after checkpointing; replacements resume, heal, trace, and replay through a shared durable companion service plane. |
| [`app_shapes/cemaf_langgraph_lcel_poc.py`](app_shapes/cemaf_langgraph_lcel_poc.py) | CEMAF as outer DAG/runtime with a real LangGraph + LCEL workflow behind an adapter node. |

## Context layers (the namesake capability)

How CEMAF assembles a prompt from layered, prioritized, budgeted context.

| Example | Proves |
|---|---|
| [`context_layers/memory_scope_hierarchy.py`](context_layers/memory_scope_hierarchy.py) | Same fact layered at GLOBAL/TENANT/SESSION; recall sees every layer, narrow scope overrides broad. |
| [`context_layers/context_type_layers.py`](context_layers/context_type_layers.py) | Typed `ContextSource` layers compiled under a `TokenBudget` — low-priority layers dropped, not truncated. |
| [`context_layers/layered_compile_pipeline.py`](context_layers/layered_compile_pipeline.py) | Full stack: `ContextPatch` (provenance) → `Context` → priority compile → budgeted prompt. |

## The whole engine

| Example | Proves |
|---|---|
| [`composed_engine.py`](composed_engine.py) | One DAG threads council → auction → agent → online-eval → harvest. |
| [`release_engine.py`](release_engine.py) | Flagship: a real release-notes engine, end-to-end (`--dry-run`/`--produce`/`--wipe`). |
| [`retrieval_dag_example.py`](retrieval_dag_example.py) | Large-scale retrieval → token-budgeted compaction → analysis. |

## Single-capability demos

[`collision_avoidance.py`](collision_avoidance.py) ·
[`security_clearance.py`](security_clearance.py) ·
[`session_snapshot.py`](session_snapshot.py) ·
[`scoped_blueprint_harvest.py`](scoped_blueprint_harvest.py)

## Local LLM (needs a running Ollama daemon)

[`ollama_gemma.py`](ollama_gemma.py) · [`ollama_gemma_tiered.py`](ollama_gemma_tiered.py)
— the CLI paths use a real Ollama daemon; the smoke harness runs deterministic
offline `smoke_main()` paths over the same CEMAF wiring.

## Before you reimplement

If you're about to hand-roll orchestration, memory, retries, budgets, or a
citation ledger, read [`anti_patterns/README.md`](anti_patterns/README.md) first.
