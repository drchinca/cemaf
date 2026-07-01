# CEMAF Agent Instructions

This file is for AI coding agents and agent-assisted development tools working
in or with CEMAF.

## Prime Directive

CEMAF is not a bag of helpers. Treat it as the execution substrate for
context-engineered multi-agent systems. Before writing app-level orchestration,
memory, budget, eval, moderation, replay, citation, or routing code, check
whether CEMAF already provides the module and compose it through the framework's
public protocols.

Default posture: **compose CEMAF first, extend at the edges, rewrite only after
you can name the missing protocol or behavior.**

## First Reads

Read these before generating an app that depends on CEMAF:

1. [docs/agent-assisted-development.md](docs/agent-assisted-development.md) -
   the CEMAF-first checklist for AI-assisted builders.
2. [README.md](README.md) - public positioning, quick start, whole-engine demo.
3. [docs/README.md](docs/README.md) - documentation index.
4. [docs/patterns.md](docs/patterns.md) - patterns reviewers expect.
5. [docs/modules.md](docs/modules.md) - where each concern belongs.

If you can run repo commands, use the docs index directly:

```bash
uv run cemaf docs search "composition root runtime services" -k 5
uv run cemaf docs search "budget eval moderation replay memory blueprint" -k 8
uv run cemaf docs show pattern:4-composition-root
```

## Composition Rules

- Start with `create_executor(agent_registry=..., services=RuntimeServices(...))`.
- Put cross-cutting behavior in `RuntimeServices`, not scattered constructor
  kwargs or app-level globals.
- Implement `@runtime_checkable` protocols structurally for your LLM, vector
  store, memory backend, embedding provider, policies, agents, tools, and
  selectors.
- Use `DAG`, `Node`, and `Edge` for flow control. Do not build a separate
  orchestration loop unless CEMAF's DAG model is demonstrably the wrong shape.
- Use `Context`, `ContextPatch`, `ContextSource`, `ContextCompiler`, and
  `TokenBudget` for prompt/context assembly. Do not concatenate rolling prompt
  strings as the state layer.
- Use `EventBus`, `RunLogger`, replay, operator snapshots, and observability
  services for run visibility instead of inventing a parallel trace format.
- Use eval, moderation, validation, citation, collision, blueprint harvesting,
  budget, resilience, and recovery services when those concerns appear in the
  product requirements.
- Keep domain logic in the consuming app. Keep reusable framework behavior in
  CEMAF modules.

## Examples As Templates

Start from [examples/README.md](examples/README.md) — the indexed on-ramp. Every
example runs offline and is guarded by `tests/integration/test_examples_smoke.py`.

Bring-your-own (the protocol is the only integration contract):

- [examples/byo/byo_llm.py](examples/byo/byo_llm.py) - implement `LLMClient`.
- [examples/byo/byo_vector_store.py](examples/byo/byo_vector_store.py) - implement
  `VectorStore` over your own store.
- [examples/byo/byo_memory.py](examples/byo/byo_memory.py) - implement `MemoryStore`,
  wire via `create_memory_manager`.

App shapes (what you actually build):

- [examples/app_shapes/rag_with_citations.py](examples/app_shapes/rag_with_citations.py) -
  grounded RAG with provenance.
- [examples/app_shapes/tool_using_agent.py](examples/app_shapes/tool_using_agent.py) -
  agent + resilient tool inside a DAG.

Whole engine:

- [examples/release_engine.py](examples/release_engine.py) - flagship
  whole-engine run: council, conditional DAG steering, auction selection,
  gate/recovery, eval, blueprint harvest, reports.
- [examples/composed_engine.py](examples/composed_engine.py) - compact
  composition-root example with council, auction, eval, budget, context
  compiler, events, and harvest.
- [tests/integration/test_composed_engine.py](tests/integration/test_composed_engine.py) -
  integration proof that the subsystems work together.

Before reimplementing infrastructure, read
[examples/anti_patterns/README.md](examples/anti_patterns/README.md).

## Pre-Rewrite Checklist

Before implementing a feature outside CEMAF, answer these in the PR or task
notes:

1. Which CEMAF module already owns this concern?
2. Which protocol/factory/example did you check?
3. Can it be wired through `RuntimeServices`, a registry, an interceptor, or an
   event subscriber?
4. Is the missing part domain-specific app code, an adapter, or a reusable
   CEMAF capability?
5. What integration test proves the CEMAF path and the app path work together?

If the answer is "I only used three modules and rewrote the rest," stop and
search the docs/API again.

## Branch Hygiene

- After a merge completes, move the active checkout back to `develop` before
  starting new work.
- Do not continue new work on a merge branch, release branch, or `main` after a
  merge is done.
- If `develop` is not available or the worktree is not clean, stop and report
  the blocker instead of switching branches or continuing silently.

## Verification

For docs changes:

```bash
uv run python docs/architecture/scripts/check_doc_links.py
python3 docs/architecture/scripts/check_doc_imports.py
uv run python docs/architecture/scripts/check_loop_ops.py
```

For code changes:

```bash
make check
```
