# CEMAF Architecture

The canonical statement of the software architecture we build toward in this repo. New contributors read this first; reviewers enforce it on every PR.

Related docs: [**Design Patterns**](patterns.md) · [**Module Layout**](modules.md)

---

## Table of contents
- [One-paragraph summary](#one-paragraph-summary)
- [The two layers](#the-two-layers)
- [Dependency rules](#dependency-rules)
- [Composition root](#composition-root)
- [Data flow for a single run](#data-flow-for-a-single-run)
- [What we say no to](#what-we-say-no-to)
- [Cost model: PULL context and unit-of-work nodes](#cost-model-pull-context-and-unit-of-work-nodes)
- [How to extend CEMAF](#how-to-extend-cemaf)

---

## One-paragraph summary

CEMAF is a **protocol-first, composable framework for running multi-agent LLM workloads with provenance**. Every integration point is a `@runtime_checkable` Protocol, every value object is a frozen dataclass or frozen Pydantic model, every cross-cutting concern (budget, eval, memory, logging, moderation) arrives via a single `RuntimeServices` bundle injected at the composition root. There is exactly one way to wire an executor (`bootstrap.create_executor`) and one immutable shape for a run's state (`Context` + `ContextPatch`). A second, opt-in layer lets CEMAF use its own primitives to spec, scaffold, and audit itself.

---

## The two layers

```
┌─────────────────────────────────────────────────────────────────────┐
│                          LAYER 2  —  Self-Hosting                    │
│                                                                      │
│    audit/         meta/                     knowledge/              │
│    EventBus →     MetaArchitect             Entities as             │
│    AuditEntry     MetaSpecifier             MemoryItems,            │
│    trail,         MetaSynthesizer           relation indexes        │
│    z-score        MetaAuditor                                       │
│    anomaly        MetaKnowledgeGraph                                │
│                   MetaScaffolder                                    │
│                                                                      │
│                      ▲                                               │
│                      │ one-way dependency                            │
│ ─────────────────────┴─────────────────────────────────────────────  │
│                          LAYER 1  —  Base Framework                  │
│                                                                      │
│   Orchestration        Agents & Execution       Context Engineering  │
│   • DAGExecutor        • Agent protocol          • Context           │
│   • Context-           • Skill protocol          • ContextPatch      │
│     NodeExecutor       • Tool protocol           • ContextCompiler   │
│   • node_handlers      • AgentRegistry           • TokenBudget       │
│     (router/loop/       • ToolRegistry            • ContextSource    │
│      parallel/                                                       │
│      conditional)                                                    │
│                                                                      │
│   Memory & Retrieval   LLM Integration           Quality & Safety    │
│   • MemoryManager      • LLMClient protocol      • EvalPipeline      │
│   • SemanticStore      • 6 adapters              • QualityPolice     │
│   • EpisodicStore      • ResilientLLMClient      • Moderation        │
│   • TieredStore        • ModeratingLLMClient     • Citation          │
│   • VectorStore        • InstrumentedLLMClient   • Validation        │
│                                                                      │
│   Blueprint Triad                                                    │
│   • BlueprintLibrary (3 entry kinds: SNAPSHOT / FACTORY / RECIPE)    │
│   • WritableBlueprintSource protocol + SqliteBlueprintSource         │
│   • BlueprintSelectorHook (wired into ContextNodeExecutor)           │
│   • BlueprintHarvesterEngine + 3 decision protocols (HarvestPolicy, │
│     RunCorrelator, BlueprintDistiller) — see docs/blueprints.md     │
│                                                                      │
│   Infrastructure                                                     │
│   • EventBus  •  Resilience  •  Persistence  •  Replay              │
│   • Observability (structured logger, prometheus metrics, budget    │
│     guard, health monitor, run logger, glass-box audit)             │
│   • MCP (adapter, bridges, transports)                              │
│                                                                      │
│   Composition root: bootstrap.create_executor(                       │
│       agent_registry,                                                │
│       services=RuntimeServices(...),   # 15+ optional deps           │
│       config=ExecutorConfig(...),       # sizing / timeouts          │
│   )                                                                  │
└─────────────────────────────────────────────────────────────────────┘
```

**Layer 1 (base framework)** — standalone, single-process, single-tenant by design. Every module imports only from other Layer 1 modules or from `core/`. No module imports from Layer 2. Every integration point is a Protocol; every default implementation is paired with a protocol and a factory.

**Layer 2 (self-hosting)** — opt-in modules that *consume* the base framework to introspect, audit, spec, and extend it. `audit/`, `knowledge/`, and `meta/` live here. They import freely from Layer 1 — the reverse is forbidden by an import invariant enforced by review.

---

## Dependency rules

These are load-bearing. Every PR is checked against them.

1. **No cycles.** If module A imports from module B, module B MUST NOT import from module A. This is enforced at import time — cycles break Python.

2. **Layer 2 → Layer 1 only.** `audit/`, `knowledge/`, `meta/` import from Layer 1. Layer 1 never imports from Layer 2. If a Layer 1 module needs something Layer 2 has, the design is wrong — promote the primitive to Layer 1 or rethink the split.

3. **Protocols in `protocols.py`, defaults next to them.** Every package has a `protocols.py` (or an equivalent file named for the primary protocol, e.g. `llm/protocols.py`) declaring the `@runtime_checkable` contracts. Default implementations live in sibling files (`llm/anthropic.py`, `memory/sqlite_store.py`). Callers depend on the Protocol, not the concrete class.

4. **`core/` depends on nothing.** `cemaf.core` holds types, enums, `Result[T]`, `utc_now()`, `generate_id()`. It is the bottom of the stack. No feature module imports are allowed into `core/`.

5. **`orchestration/` is the top of Layer 1.** It imports from every other Layer 1 module but nothing imports from it except Layer 2 and test/example code.

6. **Features inject, they do not import globals.** No feature module reads `_logger` / `_metrics` / config singletons at module level. Cross-cutting deps arrive through `RuntimeServices` at the composition root. The `observability/config.py` globals exist only as fallbacks for standalone scripts; production runs pass a configured `RunLogger` through services.

7. **Tests go through the public API.** `tests/unit/<package>/…` tests never import from `_private` helpers. If a test needs access to internal state, that's a signal to widen the protocol or add a factory — not to dot into privates.

---

## Composition root

There is **exactly one way** to build a runnable executor from application code:

```python
from cemaf.bootstrap import create_executor
from cemaf.orchestration.services import RuntimeServices
from cemaf.orchestration.executor import ExecutorConfig

executor = create_executor(
    agent_registry=registry,
    services=RuntimeServices(
        event_bus=bus,
        memory_manager=memory,
        session_manager=sessions,
        context_compiler=compiler,
        token_budget=budget,
        budget_guard=guard,
        quality_police=police,
        online_eval_pipeline=evals,
        moderation_pipeline=moderation,
        llm_client=llm,
        vector_store=vectors,
        run_logger=logger,
        health_monitor=health,
        auto_heal_manager=heal,
        domain_context=domain,
        blueprint_library=library,       # searchable Blueprint catalog
        blueprint_selector=selector,     # runtime retrieval hook (optional)
    ),
    config=ExecutorConfig(
        max_parallel=10,
        enable_events=True,
        enable_logging=True,
        enable_moderation=True,
        node_timeout_seconds=300.0,
    ),
)
```

Every field of `RuntimeServices` is optional. The framework degrades gracefully when a service is absent — `MemoryManager=None` means no memory recall, `BudgetGuard=None` means no cost cap. **Nothing crashes because a service wasn't configured.**

Why this shape:
- **Request-scoped DI for free.** One `RuntimeServices` per request gives per-request observability context, per-tenant budget guards, per-user quality police.
- **Typed, not stringly-keyed.** Mypy sees every field; wiring errors show up at type-check time, not runtime.
- **Future-proof.** The next halt signal, the next rate-limit controller, the next SLO tracker lands on `RuntimeServices`. The executor constructor does not grow a 14th kwarg.

Self-hosting applications use `meta.bootstrap.create_meta_executor(...)` which wraps `create_executor` and auto-wires the audit trail and knowledge graph from the same services bundle.

---

## Data flow for a single run

```
  caller
    │
    ▼
  executor.run(dag=dag, initial_context=ctx, run_id=rid)
    │
    ├─► set per-run ContextVars (_route_choices, _correlation_id)
    │
    ├─► topological sort of DAG
    │
    └─► for each node in order:
          │
          ├─► NodeHandlerContext bound with should_halt callback
          │
          ├─► dispatch by NodeType (AGENT / ROUTER / LOOP / PARALLEL / CONDITIONAL)
          │
          ├─► _execute_with_retry(node, context)
          │     │
          │     ├─► _try_once: resolve inputs, execute, apply output, record budget
          │     │
          │     ├─► if success → return (result, new_context)
          │     │
          │     ├─► if fail → _try_heal via AutoHealManager
          │     │     │
          │     │     └─► context changed? retry with healed context
          │     │
          │     └─► else sleep (exponential backoff), retry
          │
          ├─► ContextPatch applied to Context (immutable, new state)
          │
          ├─► moderation.check_output on flattened output (if configured)
          │
          ├─► budget.should_halt()  ← HaltSignal propagates
          │
          ├─► quality.should_halt()  ← HaltSignal propagates
          │
          ├─► emit TASK_COMPLETED event (EventBus → OnlineEvalPipeline)
          │
          └─► record patch + link in RunLogger (for replay)
    │
    ├─► reset per-run ContextVars
    │
    └─► return ExecutionResult(status, node_results, final_context, ...)
```

Key invariants in this flow:
- **`Context` is never mutated.** Every change is a new `Context` via `context.apply(patch)`. `patch_history` on the context is the full provenance chain.
- **`ContextVar` for per-run state.** `_route_choices_var` and `_correlation_id_var` are set at `run()` entry and `reset()` in `finally`. Concurrent runs on one executor instance don't collide; sequential runs in one task don't inherit stale state.
- **Halt signals carry reasons.** `HaltSignal(reason, source, detail)` — the executor logs WHICH controller fired and WHY, not just "True".
- **Every billed call counts.** `BudgetGuard.record_usage` is invoked inside `_execute_with_retry`, so LOOP bodies and failed-but-billed calls accumulate toward the cap.

---

## What we say no to

Being explicit about what this architecture rejects is as important as saying what it accepts.

- **Module-level singletons in feature modules.** `_memory_manager = MemoryManager()` at import time is forbidden. Features take their deps via constructor or `RuntimeServices`. The only module-level globals are in `core/`, `observability/config.py` (opt-in), and a ContextVar or two.
- **Inheritance-based plugin systems.** You do not subclass `AgentBase` and override methods. You implement the `Agent[GoalT, ResultT]` Protocol structurally. This keeps test doubles trivial and `isinstance` checks honest.
- **String-keyed service lookup.** No `container.get("llm_client")` pattern. Services arrive typed on `RuntimeServices`.
- **Hidden I/O in hot paths.** `Context`, `ContextCompiler`, `BudgetGuard` are sync and allocation-cheap. Any code path called once per token or once per context-selection iteration must not do I/O. Protocol implementations that DO I/O (memory stores, LLM clients) are always async and explicit.
- **Backwards-compatibility shims by default.** Greenfield-first: delete the old code, don't keep two paths. The one exception — the 0.3.x `DAGExecutor` kwargs bridge — is documented and scheduled for removal in 0.4.
- **Bare `except Exception`.** Every exception catch names the types it handles. `asyncio.CancelledError` re-raises. Silent swallows are a correctness bug (they hide tenant data or cost corruption).
- **`Any` in public APIs.** Protocol methods, dataclass fields, registry keys all use concrete types. `Any` in tests is acceptable; in public types it's a design smell.
- **Mocking with `patch()`.** If a test needs `unittest.mock.patch()`, the code under test has hidden coupling. Refactor it to take the dep as a parameter.

---

## Cost model: PULL context and unit-of-work nodes

This is a structural claim, not a tuning knob. It is what makes CEMAF different from message-bus agent frameworks, and it is the reason the same executor runs `2 + 2` and a multi-agent SQL-generation pipeline without the former subsidizing the latter's infrastructure cost.

### The thing we reject

Message-bus agent frameworks (the dominant shape in 2025) are PUSH systems. Each step is an LLM turn against a rolling shared state; every capability you attach — intent detection, routing, judges, memory recall, quality gates, tool choice — fires on **every** step because the framework doesn't know which steps need it. Ask the system `2 + 2`, and it still pays for all of it. Floor cost equals ceiling cost. This is the hidden tax of the "everything is a chatty message turn" abstraction.

The consequence in production: adding one evaluator, one gate, one memory tier multiplies the cost of every trivial step. Teams respond by disabling infrastructure, not by expressing where it should run.

### The thing we build

CEMAF is PULL. Four rails enforce it:

1. **Typed node types with separate handlers.** `NodeType.TOOL`, `NodeType.AGENT`, `NodeType.ROUTER`, `NodeType.LOOP`, `NodeType.PARALLEL`, `NodeType.CONDITIONAL`, `NodeType.CHECKPOINT` each dispatch to a different handler in `node_handlers.py`. Deterministic work (`TOOL`) cannot accidentally become an LLM call; LLM-backed work (`AGENT`) is a different code path. The type system makes it structurally impossible to pay LLM cost on a tool node.

2. **`input_mapping` is a PULL contract.** Nodes declare the context keys they consume: `input_mapping={"a": 2, "b": 2}` or `input_mapping={"text": "$$analysis$$"}`. The executor resolves exactly those keys. There is no "give this step all the accumulated state" default — the rolling-history firehose pattern is inexpressible.

3. **Services are opt-in `| None` fields on `RuntimeServices`.** `online_eval_pipeline`, `memory_manager`, `budget_guard`, `moderation_pipeline`, `quality_police` — all absent by default. The executor checks for `None` before every call site. `create_executor(agent_registry=registry)` with no services attached pays zero infrastructure cost. You don't disable features; you simply don't compose them.

4. **Evaluators bind to node patterns, not the whole DAG.** `NodeEvalBinding(node_pattern="generate_sql", ...)` attaches a judge to one node. `node_pattern="*"` is *available*, not the default. The author declares *where* quality matters. Checkpoints are explicit `NodeType.CHECKPOINT` nodes — you place them where they earn their cost.

```python
# Trivial work, trivial cost — no LLM, no eval, no memory recall, no router.
DAG(
    name="arithmetic",
    nodes=(Node(
        id=NodeID("add"),
        type=NodeType.TOOL,
        ref_id="add",
        input_mapping={"a": 2, "b": 2},
    ),),
    edges=(),
    entry_node=NodeID("add"),
)
executor = create_executor(agent_registry=registry)  # no RuntimeServices → nothing attached
await executor.run(dag=dag)  # → 4, one tool call, nothing else billed

# LLM work with quality telemetry — judge runs in the background, does not block the hot path.
pipeline = OnlineEvalPipeline(
    bindings=(NodeEvalBinding(
        node_pattern="generate_sql",
        evaluators=(LLMJudge(),),
        mode=EvalMode.OBSERVE,   # fire-and-forget; GATE would serialize
    ),),
    event_bus=bus,
)
executor = create_executor(
    agent_registry=registry,
    services=RuntimeServices(event_bus=bus, online_eval_pipeline=pipeline),
)
```

### `OBSERVE` vs `GATE` — the temporal dimension

Every cross-cutting signal has two distinct semantics the framework exposes:

- **`OBSERVE`** — I want this telemetry, but it must not serialize the pipeline. Evaluator runs in a task the pipeline tracks in its `_pending` set; `TASK_COMPLETED` publish returns immediately; next node starts; judge completes in the background; `EVAL_COMPLETED` lands whenever it lands. `OnlineEvalPipeline.flush()` awaits every in-flight OBSERVE task for this pipeline — production graceful shutdown, tests, or any code that needs to know all scheduled evals have landed. Used for quality monitoring, SLO tracking, drift detection.
- **`GATE`** — this signal *must* land before the next node runs. Evaluator runs inline; `QUALITY_ALERT` publishes before `publish()` returns; `should_halt()` observes the alert; the executor honors the halt. Used for safety-critical gates: a failing eval must stop downstream work.

Both modes exist in the same pipeline, per-binding. One node can be OBSERVE, its downstream node can be GATE. This is the control you do not get from a message-bus framework, where "run a judge after this step" means "block the pipeline on the judge" unconditionally.

### The claim

The payoff is not "CEMAF makes `2 + 2` cheap." Any framework can skip infrastructure on a trivial task if the author remembers to flag it. The structural payoff is:

> A pipeline containing both `2+2` and an LLM-backed SQL generator pays appropriately for each.

The trivial node cannot subsidize the expensive node's infrastructure. The expensive node's judge cannot block the trivial node. The author expresses *where* each capability runs, and the framework composes that expression without leaking cost across boundaries.

This is how we think context engineering should be done. Context is a compiled, auditable asset with provenance (`Context` + `ContextPatch` + `ContextCompiler` against a `TokenBudget`) — not a prompt you glue together with f-strings. Agents are typed units of work with declared input/output contracts — not opaque turns on a chatty loop. Quality, cost, memory, and safety are cross-cutting services injected at the composition root — not sprinkled implicitly between every step. If a framework does not give you these separations, the cost model is an accident of its abstraction; you cannot reason about it without reading the dispatch loop.

We treat this as the default. It is not a tuning setting.

---

## How to extend CEMAF

Three shapes cover 95% of extensions:

**1. Bring Your Own Backend.** You have a different LLM, vector store, embedding provider, or memory backend. Find the protocol in `<package>/protocols.py`, implement it, pass your instance in through `RuntimeServices`. No fork, no inheritance.

```python
class MyPgVectorStore:
    async def search(self, query_embedding, k=10, filter=None): ...
    async def add(self, document): ...

services = RuntimeServices(vector_store=MyPgVectorStore())
```

**2. New Agent.** Subclass `Agent[GoalT, ResultT]`. Register it. Done.

```python
class GradingAgent(Agent[GradeGoal, GradeResult]):
    @property
    def id(self) -> AgentID: return AgentID("Grader")
    @property
    def description(self) -> str: return "Grades student submissions"
    @property
    def skills(self) -> tuple[()]: return ()
    async def run(self, goal, context): ...

registry.register_agent(agent_instance=GradingAgent(), goal_type=GradeGoal)
```

**3. New Cross-Cutting Controller.** You need to add a new kind of gate (rate limit, SLO tracker, tenant budget). Add the field to `RuntimeServices`. Wire it in the executor's `_halt_signal` and `_try_once`. Register a `HaltReason` for it. Done.

Anti-patterns when extending:
- Do not add a new kwarg to `DAGExecutor.__init__`. Use `RuntimeServices`.
- Do not create a new `__init__.py` global. Use a factory function in the package.
- Do not import from Layer 2 into Layer 1.

See [docs/patterns.md](patterns.md) for the canonical design patterns and [docs/modules.md](modules.md) for where each kind of thing lives.
