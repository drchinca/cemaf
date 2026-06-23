# CEMAF

**Context Engineering Multi-Agent Framework**

[![Open Source](https://img.shields.io/badge/Open%20Source-%E2%9D%A4-red?style=flat-square)](https://opensource.org)
[![Project Status: Alpha](https://img.shields.io/badge/Status-Alpha-yellow?style=flat-square)](https://github.com/drchinca/cemaf)
[![Discord](https://img.shields.io/badge/Discord-Join_Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/C8ZXAbD8)
[![Python](https://img.shields.io/badge/Python-3.14+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/Tests-3400+_Passing-success?style=flat-square&logo=pytest&logoColor=white)](.)
[![Coverage](https://img.shields.io/badge/Coverage-80%25-brightgreen?style=flat-square)](.)
[![CI](https://img.shields.io/github/actions/workflow/status/drchinca/cemaf/ci.yml?branch=main&style=flat-square&logo=github&label=CI)](https://github.com/drchinca/cemaf/actions/workflows/ci.yml)
[![Ruff](https://img.shields.io/badge/Code_Style-Ruff-FCC21B?style=flat-square&logo=ruff&logoColor=black)](https://github.com/astral-sh/ruff)
[![MyPy](https://img.shields.io/badge/Typed-MyPy-blue?style=flat-square)](http://mypy-lang.org/)
[![Stars](https://img.shields.io/github/stars/drchinca/cemaf?style=flat-square&logo=github)](https://github.com/drchinca/cemaf)
[![Issues](https://img.shields.io/github/issues/drchinca/cemaf?style=flat-square&logo=github)](https://github.com/drchinca/cemaf/issues)
[![Open Startup](https://img.shields.io/badge/Open-Startup-00ADD8?style=flat-square)](OPEN.md)

**Open source** context engineering infrastructure that solves the hard problems in AI agent systems. CEMAF can be used standalone or plugged into existing frameworks like LangGraph, AutoGen, and CrewAI.

> **See it run — 60 seconds.** Open [`docs/architecture/cemaf-graph.html`](docs/architecture/cemaf-graph.html) in a browser. Two tabs:
> - **Module graph** — every module in `src/cemaf/` as a node, every `import` as an edge, AST-exact (regenerate with [`docs/architecture/build_graph_data.py`](docs/architecture/build_graph_data.py)).
> - **DAG process** — 7 progressive runs (`hello → chain → parallel → council → auction → gate → full flow`) showing real `EventBus` output from actual `executor.run(dag)` calls. Generate fresh traces with [`uv run python docs/architecture/scripts/produce_dag_trace.py`](docs/architecture/scripts/produce_dag_trace.py).
>
> Deeper read: [`docs/architecture/deep-architecture.md`](docs/architecture/deep-architecture.md) · [`docs/architecture/cemaf-architecture.html`](docs/architecture/cemaf-architecture.html) (interactive atlas) · [`docs/architecture/spec-module-map.md`](docs/architecture/spec-module-map.md).

### The dual DAG · agents on top, context below

```
   AGENT DAG  ─────────────────────────────────────────────────
   bp ─→ lib ─→ research ─→ council(3) ─→ writer.fast(auction)
                                              │
                      cite ─→ gate ─→ publish │   recover lane
                                              │   ─────────────
                                              │   gate↯ → heal → writer.attempt2
                                              ↓
   CONTEXT DAG  ────────────────────────────────────────────────
   blueprint  KG  memory[L0/L1/L2]  research.findings  draft.body
   citations  session→PROJECT
   ─────────────────────────────────────────────────────────────
   ↑ every read/write a wire · every patch carries source + reason + run_id
```

CEMAF treats every agent decision and every context byte as a **first-class structured event**. One `executor.run(dag)` emits a typed stream — `task.started`, `council.ballot(weight)`, `auction.bid(fitness, load)`, `auction.award(saved_p95_ms)`, `citation.added(statement, src, supported, strength)`, `eval.completed(composite, sub, verdict)`, `memory.hit(tier)`, `blueprint.harvested(score)`, `dag.completed`. **Glass-box by default**, not by configuration.

### What CEMAF makes the industry standard

The agentic-AI ecosystem ships glue code; CEMAF ships the rails the industry has been re-implementing for two years.

| Hard problem the field keeps re-solving | CEMAF's standard | Spec |
|---|---|---|
| "How do I keep agents from blowing the token budget?" | `Context` is immutable, compiled per-turn under a `TokenBudget` with priority selection. Every byte has provenance. | [SPEC-00](docs/specs/SPEC-00-enterprise-context-brain.md) |
| "How do I prove an LLM output is grounded?" | `CitationTracker` + `GateEvalInterceptor` enforce citation-membership: every factual statement must trace to a retrieved source, or the gate halts downstream. | [SPEC-05](docs/specs/SPEC-05-guardian-mesh.md) · [SPEC-01a](docs/specs/SPEC-01a-interceptor-spine.md) |
| "How do I pick between 3 agents that could all do the job?" | Auction selection: agents bid by `fitness × (1 - load)`; ballot is preserved in `NodeResult.metadata` for audit. | [SPEC-09](docs/specs/SPEC-09-auction-agent-selection.md) |
| "How do I get N agents to agree?" | Council node-kind: deliberative vote with pluggable `VoteAggregator` (majority / weighted / quorum / unanimous) and a persisted ballot trail. | [SPEC-10](docs/specs/SPEC-10-agent-council.md) |
| "What happens when an LLM call fails the eval?" | `RECOVER` budget (`max_recovery_attempts ≤ 2`), `AutoHealManager` mutates the goal with `FailureSignal` context, agent re-runs with a patched goal. | [SPEC-08](docs/specs/SPEC-08-failure-feedback-loop.md) |
| "How do I observe this in production?" | OTel GenAI-shape events on the `EventBus` (`gen_ai.request.model`, `usage.input_tokens`, `cost_usd`, `span`), `correlation_id` propagation, structured logs, Prometheus metrics. | [observability.md](docs/observability.md) |
| "How do I integrate with my existing stack?" | Every integration is a `@runtime_checkable` `Protocol` (LLM client, vector store, embedding provider, memory backend, agent selector, vote aggregator, …). **BYO-X** — structural typing, no inheritance. | [patterns.md](docs/patterns.md) |
| "How do I scale a successful run into a reusable template?" | `BlueprintHarvesterEngine` subscribes to `EVAL_COMPLETED`, distills high-quality runs into reusable `Blueprint`s, persists them via `create_blueprint_harvester(library, ...)`, and exposes them via `BlueprintLibrary.search(...)`. The flywheel is a Protocol-driven engine, not a script. | [SPEC-03](docs/specs/SPEC-03-blueprint-as-llm-input.md) |
| "Where does the framework end and my code begin?" | `RuntimeServices` frozen dataclass with ~20 optional `Protocol`-typed fields. `bootstrap.create_executor(services=...)` is the composition root. **No module-level singletons. No magic.** | [SPEC-00](docs/specs/SPEC-00-enterprise-context-brain.md) · [patterns.md](docs/patterns.md) |

<details><summary><b>Where these primitives live</b> (copy-paste imports)</summary>

```python
from cemaf.context                 import Context, ContextPatch, TokenBudget, PriorityContextCompiler
from cemaf.citation                import CitationTracker
from cemaf.interceptors            import GateEvalInterceptor
from cemaf.agents.selection        import AgentSelector         # auction selection
from cemaf.council                 import VoteAggregator, DefaultVoteAggregator
from cemaf.core.recovery           import AutoHealManager
from cemaf.iteration               import FailureSignal
from cemaf.blueprint               import Blueprint, BlueprintLibrary, BlueprintHarvesterEngine, create_blueprint_harvester
from cemaf.orchestration           import DAG, Node, Edge, DAGExecutor
from cemaf.orchestration.services  import RuntimeServices
from cemaf.bootstrap               import create_executor
```

Live-verified at HEAD on every CI run — every name above resolves against `src/cemaf/`.

</details>

[**See it run — open the interactive demo →**](docs/architecture/cemaf-graph.html)

---

## Table of Contents

- [Overview](#overview)
- [The Hard Problems We Solve](#the-hard-problems-we-solve)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Integration Modes](#integration-modes)
- [Key Features](#key-features)
- [Documentation](#documentation)
- [Configuration](#configuration)
- [Testing](#testing)
- [Contributing](#contributing)
- [Getting Help](#getting-help)
- [Philosophy & Open Startup](#philosophy--open-startup)
- [License](#license)

---

## Overview

CEMAF is a protocol-first framework for **context engineering** in multi-agent AI systems. It owns the hard infrastructure problems — token budgeting, provenance, memory scoping, eval, moderation, resilience, self-hosting — while staying framework-agnostic. Use it standalone or drop modules into LangGraph / AutoGen / CrewAI.

- **Protocol-first**: every integration point is a `@runtime_checkable` Protocol. Bring your own LLM, vector store, memory backend, embedding provider. Structural typing, no inheritance required.
- **Immutable context with provenance**: `Context.apply(patch)` — every context change is an auditable `ContextPatch`. Replay, debug, and grade any past run deterministically.
- **Composition root**: `create_executor(services=RuntimeServices(...), config=ExecutorConfig(...))` wires 15+ optional services into one typed bundle. Request-scoped DI shape, no module-level singletons.
- **Self-hosting meta-layer**: CEMAF uses CEMAF to introspect, audit, spec, and extend itself. One instruction becomes a runnable CEMAF-based app on disk.

---

## A different shape of agent system

Most agent frameworks are message-bus PUSH systems. Every step is an LLM turn against a rolling shared state; every capability you add (eval, intent detection, memory, routing, gates) is paid on *every* step. Ask the system `2 + 2` and it still pays for an intent classifier, a judge, a memory recall, and a router. Floor cost = ceiling cost.

CEMAF is PULL. Nodes are **typed units of work** that declare what they need (`input_mapping={"a": 2, "b": 2}`) and the executor resolves exactly that — no ambient state firehose. Context compiles per-turn within a `TokenBudget` with priority selection. Services (eval, moderation, memory, budget) live in `RuntimeServices` as `| None` fields — absent = never runs. Evaluators bind to node patterns, not "every step." `NodeType.TOOL` is a different handler from `NodeType.AGENT`; deterministic work doesn't accidentally become an LLM call.

```python
# Deterministic work pays deterministic cost. No LLM, no eval, no recall.
DAG(nodes=(Node(type=NodeType.TOOL, ref_id="add", input_mapping={"a": 2, "b": 2}),), ...)
create_executor(agent_registry=registry)   # no services attached → nothing to pay for

# LLM work with quality telemetry. OBSERVE runs in the background — never blocks the hot path.
NodeEvalBinding(node_pattern="generate_sql", evaluators=(LLMJudge(),), mode=EvalMode.OBSERVE)
```

The payoff isn't "CEMAF makes 2+2 cheap." It's that a pipeline containing both `2+2` and an LLM-backed SQL generator **pays appropriately for each**. The trivial node doesn't subsidize the expensive node's infra cost. Message-bus frameworks can't easily express that — everything is an LLM turn against a shared rolling state, so the floor cost is the ceiling cost.

This is a different way to build software. We treat context as a compiled, auditable asset with provenance — not a prompt you glue together. We treat agents as typed units of work with declared contracts — not opaque turns on a chatty loop. The rails that keep it honest (typed node types, opt-in `RuntimeServices`, pattern-bound evals, OBSERVE vs GATE, immutable `Context` + `ContextPatch`) are the framework; the framework isn't a collection of helpers you remember to use.

Full treatment: [`docs/architecture.md#cost-model-pull-context-and-unit-of-work-nodes`](docs/architecture.md#cost-model-pull-context-and-unit-of-work-nodes).

---

## Architecture at a Glance

```
┌─────────────────────────────────────────────────────────────────────┐
│                          LAYER 2  —  Self-Hosting                    │
│   audit/  •  knowledge/  •  meta/  (MetaSpecifier, MetaScaffolder…)  │
│                              ▲                                       │
│                              │ one-way dependency                    │
│ ─────────────────────────────┴─────────────────────────────────────  │
│                          LAYER 1  —  Base Framework                  │
│                                                                      │
│  orchestration/  ──────  DAGExecutor + ContextNodeExecutor          │
│       │                  (topo sort → node dispatch → context)       │
│       ▼                                                              │
│  agents/  •  tools/  •  skills/  •  blueprint/                       │
│  context/ •  memory/ •  retrieval/ •  rlm/                          │
│  llm/     •  generation/ • streaming/                                │
│  evals/   •  moderation/ • validation/ • citation/                  │
│  events/  •  observability/ • resilience/ • persistence/            │
│  mcp/     •  cache/    • replay/    • ingestion/                    │
│                                                                      │
│  Composition root:                                                   │
│    bootstrap.create_executor(                                        │
│        agent_registry=registry,                                      │
│        services=RuntimeServices(...),    # 15+ optional deps         │
│        config=ExecutorConfig(...),        # sizing / timeouts        │
│    )                                                                 │
└─────────────────────────────────────────────────────────────────────┘
```

> **Interactive companion:** [`docs/architecture/cemaf-architecture.html`](docs/architecture/cemaf-architecture.html) — the architecture atlas. Every module placed by measured import fan-in (not by feature category). **Tier 4** is the single node hub each feature funnels through; **Tier 0** is the foundation everything depends on. Five tabs: Core Bytes · Agent Behaviours · Context Lifecycle · Runtime + Reactive · Principles.

**Read [docs/architecture.md](docs/architecture.md)** for the canonical software architecture we build toward, **[docs/patterns.md](docs/patterns.md)** for the design patterns catalog, and **[docs/modules.md](docs/modules.md)** for ideal package boundaries.

---

## CEMAF runs on CEMAF

CEMAF's self-hosting layer is its first client. Meta-agents, meta-tools, and pre-built meta-DAGs are *standard* `Agent` / `Tool` / `DAG` citizens — they run through the same `DAGExecutor` as user code. No special paths, no shadow framework.

| Meta-agent | Role | Tools |
|---|---|---|
| `MetaArchitect` | Design DAG pipelines from a feature description | `IntrospectRegistryTool`, `GenerateDAGTool` |
| `MetaSynthesizer` | Generate CEMAF agent Python source from templates | (template-based) |
| `MetaAuditor` | Analyze execution traces for quality / anomalies | `TraceAnalyzerTool` |
| `MetaKnowledgeGraph` | Query and refresh the entity knowledge graph | `KnowledgeGraphTool` |

| Pre-built DAG | Flow | Purpose |
|---|---|---|
| `self_audit` | `MetaAuditor` → audit report | Audit recent execution quality |
| `feature_synthesis` | `MetaArchitect` → `MetaSynthesizer` | Design + generate a new agent |
| `knowledge_refresh` | `MetaAuditor` → `MetaKnowledgeGraph` | Promote execution data into the KG |

Entry point: **`cemaf.meta.bootstrap.create_meta_executor()`** — wraps `create_executor()`, auto-wires audit (from `EventBus`) and KG (from `MemoryManager`), and registers all meta-agents and meta-tools.

```python
from cemaf.meta.bootstrap import create_meta_executor
from cemaf.meta.dags import create_self_audit_dag

executor = create_meta_executor()
result = await executor.run(create_self_audit_dag())

print(result.final_context.get("audit_report"))
```

See **[docs/self-hosting.md](docs/self-hosting.md)** for the full meta catalog, DAG walkthroughs, and the extension pattern for adding new meta-agents. The Enterprise Context Brain target architecture (SPEC-00..06) and where each spec concept lands in the codebase are tracked in **[docs/architecture/spec-module-map.md](docs/architecture/spec-module-map.md)**.

---

## The Hard Problems We Solve

| Problem | What Happens | CEMAF Solution |
|---------|--------------|----------------|
| **Context Growth** | Token limits blow up | Token budgeting + automatic summarization |
| **Reliability** | Non-deterministic behavior | Patch-based provenance tracking |
| **Cost** | Wasteful token usage | Smart context compilation |
| **Reproducibility** | Can't replay/debug runs | Run recording + deterministic replay |
| **Memory Leaks** | State bleeds between scopes | Strict memory boundaries with TTL |
| **Content Safety** | Harmful outputs slip through | Pre/post-flight moderation gates + PII detection |
| **Quality Drift** | Output quality degrades silently | Online eval pipeline with rolling monitors and halt gates |
| **Prompt Engineering** | Inconsistent LLM outputs | Semantic blueprints for structured content generation |
| **Spec Drift** | Code and intent diverge silently | MetaSpecifier authors OpenSpec proposals; `openspec validate --strict` is a deterministic eval signal |
| **Zero-to-App** | Going from feature idea to runnable code takes days | `app_synthesis` DAG: description → spec → DAG design → agents → scaffolded, importable CEMAF app on disk |
| **Framework Evolution** | Adding new capabilities requires hand-wiring registries, DAGs, bootstrap | Self-hosting meta-layer — CEMAF uses CEMAF to extend CEMAF |
| **Prompt Injection via Tool Results** | Retrieved docs / MCP results bypass moderation, land in the next turn | `ModeratingLLMClient` wraps any LLMClient: NFKC-normalizes, strips zero-width chars, flattens structured tool output, runs pre-flight gate |
| **Streaming Leaks Unsafe Tokens** | Chat UIs show content to users before moderation fires | Sentence-boundary buffered moderation in `stream()` — caller never sees more than one sentence of disallowed content |
| **Silent Budget Overrun** | Cost cap looks configured but never fires | `BudgetGuard` records every billed call (success OR failure) with NaN-safe accumulation; `HaltSignal(reason=BUDGET_EXHAUSTED)` propagates into loop bodies between iterations |
| **Context-Length Surprises** | Heuristic token counts under-estimate 30-50% → `400 context_length_exceeded` in prod | `count_tokens_exact(messages, tools)` via Anthropic / OpenAI / Gemini APIs + tiktoken fallback |
| **Concurrent-Run Contamination** | One `DAGExecutor` instance shared across coroutines clobbers route choices & correlation IDs | `contextvars.ContextVar` per-run state; concurrent calls on the same executor are isolated |

---

## Installation

```bash
# Core installation (minimal dependencies)
pip install cemaf

# With optional integrations
pip install "cemaf[openai]"        # OpenAI + tiktoken
pip install "cemaf[anthropic]"     # Anthropic
pip install "cemaf[tiktoken]"      # Accurate token counting only
pip install "cemaf[prometheus]"    # Prometheus metrics export
pip install "cemaf[all]"           # All optional dependencies

# Development installation
git clone https://github.com/drchinca/cemaf.git
cd cemaf
make install              # uv sync --extra dev
make check                # lint + typecheck + every doc/code audit (CI-equivalent)
make demo                 # regenerate the 7 real CEMAF run traces
make showcase             # open the interactive demo in your browser
make                      # print the full menu
```

**Requirements**: Python 3.14+

---

## Quick Start

```python
from pydantic import BaseModel
from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.core.enums import NodeType
from cemaf.core.types import AgentID, NodeID
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices


# 1. Define your goal / result types (Pydantic)
class ResearchGoal(BaseModel):
    topic: str


class ResearchResult(BaseModel):
    findings: str


# 2. Define an agent
class Researcher(Agent[ResearchGoal, ResearchResult]):
    @property
    def id(self) -> AgentID:
        return AgentID("Researcher")

    @property
    def description(self) -> str:
        return "Researches a topic and returns findings"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal, context):
        return AgentResult.ok(
            output=ResearchResult(findings=f"key findings on {goal.topic}"),
            state=AgentState(),
            # BudgetGuard / eval pipeline read these telemetry keys
            metadata={"cost_estimate_usd": 0.05, "tokens_total": 500},
        )


# 3. Wire services via RuntimeServices (budget, evals, moderation, memory…)
registry = AgentRegistry()
registry.register_agent(agent_instance=Researcher(), goal_type=ResearchGoal)

executor = create_executor(
    agent_registry=registry,
    services=RuntimeServices(),           # defaults; add budget_guard, event_bus, …
    config=ExecutorConfig(enable_events=False),
)

# 4. Build the DAG and run
dag = DAG(
    name="research",
    nodes=(
        Node(
            id=NodeID("n1"),
            type=NodeType.AGENT,
            name="research",
            ref_id="Researcher",
            input_mapping={"topic": "quantum computing"},
            output_key="findings",
        ),
    ),
    edges=(),
    entry_node=NodeID("n1"),
)

result = await executor.run(dag=dag)
print(result.final_context.get("findings"))
```

See `examples/hello_world.py` for a complete runnable example and
`tests/integration/test_full_stack.py` for a realistic 3-agent pipeline
wiring `SqliteMemoryStore`, `BudgetGuard`, `ContextCompiler`, and `EventBus`.

### The whole engine, end-to-end

`examples/release_engine.py` is the flagship — a release-notes engine that
composes the full framework into one declarative DAG: a **council** of reviewer
agents votes ship/hold → the verdict **steers** the DAG → an **auction** picks
the least-loaded writer → the draft is **quality-gated** → the run is **harvested**
into a reusable blueprint, with full provenance. It has a real run lifecycle:

```bash
uv run python examples/release_engine.py --dry-run   # plan: show stations + DAG, no side effects
uv run python examples/release_engine.py --produce   # run for real → ./.release_out/{RELEASE_NOTES.md,run_report.json}
uv run python examples/release_engine.py --wipe       # remove produced artifacts
```

This is the answer to "what is CEMAF *for*": you declare the stations, the engine
threads every subsystem through them, and you get the artifact plus the provenance
that proves how it was produced.

---

## Integration Modes

### Mode A: CEMAF Orchestrates

CEMAF owns execution, external frameworks are "engines":

```python
from cemaf.orchestration import DAGExecutor
from cemaf.observability import InMemoryRunLogger

executor = DAGExecutor(
    node_executor=LangGraphNodeExecutor(langgraph_app),
    run_logger=InMemoryRunLogger(),
)
result = await executor.run(dag, context)

# Replay later for debugging
replayer = Replayer(run_logger.get_record("run-123"))
await replayer.replay()
```

### Mode B: CEMAF as Library

External frameworks orchestrate, CEMAF provides infrastructure:

```python
from cemaf.context import Context, ContextPatch
from cemaf.observability import InMemoryRunLogger

@langgraph_node
def my_node(state):
    ctx = Context.from_dict(state)

    # Track provenance of every change
    patch = ContextPatch.from_tool("search", "results", search_results)
    ctx = ctx.apply(patch)
    run_logger.record_patch(patch)

    # Compile within budget
    compiled = compiler.compile(ctx, budget)
    return compiled.to_dict()
```

See the [Integration Guide](docs/integration.md) for detailed patterns.

---

## Key Features

### Context Engineering
- **Context Patches**: Track every context change with full provenance
- **Token Budgeting**: Stay within limits with smart compilation (greedy, knapsack, optimal algorithms)
- **Deterministic Replay**: Record and replay runs for debugging
- **Glass Box Audit**: Full provenance chain linking every LLM call to its context sources, citations, and costs
- **Context Type Classification**: RESOURCE/MEMORY/SKILL behavioral semantics with per-type compaction rules
- **Semantic Blueprints**: Structured content generation with Denis Rothman's blueprint pattern
- **Recursive LLM**: Parallel divide-and-conquer querying for 1M+ token contexts

### Memory System
- **Strict Scoping**: Memory boundaries with TTL prevent state leaks
- **Three-Tier Progressive Loading**: L0 abstract / L1 overview / L2 full content for token-efficient retrieval
- **Semantic Deduplication**: Exact key + embedding similarity detection with merge/skip resolution
- **Post-Session Extraction**: Automatic promotion of session learnings to long-term memory (patterns, corrections, facts)
- **Hierarchical Scope Propagation**: Parent-to-child score propagation for scope-aware retrieval
- **SQLite Persistence**: Production-ready persistent memory store via aiosqlite

### Online Evaluation
- **Hierarchical Judge**: Three-tier evaluation -- fast deterministic checks, semantic similarity, LLM judge (escalates only when needed)
- **Online Eval Pipeline**: Subscribe to execution events and run evaluators on node outputs in real-time
- **Quality Police**: Rolling window quality monitor with anomaly detection and automatic halt gates
- **Eval Tools & Agents**: RunEvalTool, CheckQualityTool, RecordScoreTool, QualityGuardAgent -- dogfooding the eval system as CEMAF tools
- **GroundednessEvaluator**: deterministic n-gram overlap between output and retrieved context sources — catches hallucination without an LLM judge
- **ToolUseSuccessEvaluator**: tool-call success rate × result-reference in output — detects silent tool-use failures

### LLM Integration
- **Six adapters out-of-the-box**: Anthropic, OpenAI, Gemini, Groq/Together/Fireworks (via OpenAI-compat), Ollama/vLLM/LM Studio (via OpenAI-compat), Mock
- **`count_tokens_exact(messages, tools)`** async method for pre-flight sizing: Anthropic API, OpenAI tiktoken, Gemini `:countTokens`, heuristic fallback
- **`ModeratingLLMClient`** decorator: NFKC unicode normalization + zero-width strip + structured-content flattening, runs pre-flight gate on every tool-result message before forwarding. Defends against prompt injection via retrieved docs / MCP results.
- **Streaming-aware moderation**: `stream()` buffers by sentence boundary and runs post-flight gate per completed sentence — callers never see more than one sentence of disallowed content
- **`ResilientLLMClient`**: retry (narrow transient-error list) + circuit breaker + rate limiter composing around any LLMClient

### Production Backends
- **Resilient LLM Client**: Retry with exponential backoff + circuit breaker + rate limiter composing around any LLMClient
- **OpenAI Embeddings**: Production embedding provider using text-embedding-3-small with batch support
- **Structured Logging**: JSON-lines logger with context fields for production observability
- **Prometheus Metrics**: Counter/gauge/histogram/timing export with lazy metric registration

### Orchestration
- **DAG Executor**: Topological sort, parallel execution, conditional routing, loop nodes, cooperative cancellation
- **Concurrent-Safe**: `contextvars.ContextVar` per-run state — one `DAGExecutor` instance handles N concurrent `run()` calls without clobbering route choices or correlation IDs
- **HaltSignal**: structured halt reporting with `HaltReason` enum (`BUDGET_EXHAUSTED`, `QUALITY_DEGRADED`). Propagates into LOOP bodies via `should_halt` callback so runaway loops don't burn N-1 calls after halt fires
- **Canonical constructor**: `DAGExecutor(services=RuntimeServices(...), config=ExecutorConfig(...))` — cross-cutting deps bundled, not 13 kwargs
- **Node Type Handlers**: Extracted router, conditional, loop, parallel handlers for clean separation
- **RuntimeServices**: Frozen dataclass bundling 15+ optional dependencies for composition root
- **Bootstrap**: Single `create_executor()` entry point wiring registry, services, and subscriptions
- **Context Agents**: Built-in Librarian, Researcher, Summarizer, Writer agents with dynamic registry
- **Budget Guard**: Configurable cost/token limits. Records every billed call including failures and retries. NaN-safe. Halts the DAG between nodes AND mid-loop via `HaltSignal`.

### Infrastructure
- **Protocol-Based**: Plug into any framework -- modules work standalone, extend with your own implementations
- **Extensible Registries**: ProviderRegistry pattern for pluggable LLM, compiler, and retrieval backends
- **Instrumented LLM**: Transparent LLM call recording for automatic glass box audit
- **Moderation & Guardrails**: Pre/post-flight content safety with PII detection and compliance rules
- **Configuration-Driven**: Zero-config defaults with .env customization
- **Resilience**: Retry, circuit breaker, rate limiting as composable decorators

### Self-Hosting Engine
CEMAF is its own first client — opt-in modules where the framework uses its own primitives to introspect, audit, spec, and extend itself. Fully decoupled from the base framework (one-way dependency).

- **Audit Trail**: `EventBusAuditLog` subscribes to EventBus, converts events into queryable `AuditEntry` records with quality trend analysis and z-score anomaly detection
- **Knowledge Graph**: `MemoryBackedKnowledgeGraph` — entities and relations backed by MemoryManager with semantic search and neighbor traversal
- **Meta-Agents**: `MetaArchitect` (DAG design), `MetaSpecifier` (OpenSpec proposal authoring), `MetaSynthesizer` (agent code gen), `MetaAuditor` (trace analysis), `MetaKnowledgeGraph` (KG operations), `MetaScaffolder` (runnable CEMAF-app synthesis)
- **OpenSpec Bridge**: `OpenSpecRuntime` protocol (System/Npx/Fake impls) + `OpenSpecWorkspace` (atomic writes, per-change locks) exposes `openspec validate/list/show/write/delete` as CEMAF tools
- **Pre-built DAGs**: `create_self_audit_dag()`, `create_feature_synthesis_dag()`, `create_knowledge_refresh_dag()`, `create_self_spec_dag()`, `create_app_synthesis_dag()`
- **Entry point**: `create_meta_executor()` wraps `create_executor()`, auto-wires audit + KG from `RuntimeServices` and MetaSpecifier/OpenSpec tools from `MetaServices`

**What this gets you**: one instruction ("build an app that does X") becomes a working CEMAF-based app on disk — spec validated by `openspec validate --strict`, agents synthesized from the spec, scaffolded into an importable package with its own registry, DAGs, and smoke tests. See `create_app_synthesis_dag()`.

### Blueprint Triad — the self-growing knowledge asset

`Blueprint` is CEMAF's semantic prompt object. The **triad** turns it from a reference type into a runtime asset that learns from successful runs:

- **`BlueprintLibrary`** — curated, searchable catalog. Three storage kinds (SNAPSHOT / FACTORY / RECIPE) all resolving to the same `Blueprint`. Developer-authored entries and autonomously harvested entries coexist under one `search()`.
- **`BlueprintSelectorHook`** — one-method `@runtime_checkable` Protocol wired into `ContextNodeExecutor`. Before every LLM call, the executor retrieves the best-matching blueprint's prompt and injects it into compiled context as the highest-priority artifact.
- **`BlueprintHarvesterEngine`** — autonomous write path. Subscribes to `EVAL_COMPLETED`, turns high-quality runs into RECIPE entries, appends them to a writable source. Every decision (policy, correlator, distiller) is a pluggable Protocol — bundled defaults are opt-in, not the only way.

```python
from cemaf.blueprint import BlueprintLibrary, BlueprintHarvesterEngine
from cemaf.blueprint.sqlite_source import SqliteBlueprintSource
from cemaf.meta.blueprint_selector import LibraryBlueprintSelectorHook
from cemaf.meta.harvest_defaults import (
    InMemoryRunCorrelator, RecipeBlueprintDistiller, ScoreThresholdHarvestPolicy,
)

source = SqliteBlueprintSource(db_path="blueprints.db")
library = BlueprintLibrary(); library.register_from(sources=(source,))
selector = LibraryBlueprintSelectorHook(library=library)
engine = BlueprintHarvesterEngine(
    writable_source=source, library=library,
    policy=ScoreThresholdHarvestPolicy(threshold=0.85),
    correlator=InMemoryRunCorrelator(),
    distiller=RecipeBlueprintDistiller(),
)
engine.subscribe(event_bus=bus)   # auto-harvest from now on
```

Full reference: [`docs/blueprints.md`](docs/blueprints.md). Design pattern: [`docs/patterns.md#13-protocol-gated-growing-asset-blueprint-triad`](docs/patterns.md).

---

## Docs for LLMs (`cemaf.docs_api`)

CEMAF exposes its own documentation as a first-class queryable index — so
agents reasoning about *how to use CEMAF* can look up CEMAF. The index
covers `docs/**/*.md`, each `cemaf.*` package docstring, each module
docstring, and individual design-pattern sections — 340+ entries built
automatically from the repo at startup.

```bash
# Humans — CLI search
uv run cemaf docs search "composition root runtime services" -k 3
uv run cemaf docs show pattern:4-composition-root
```

```python
# Agents — register as CEMAF tools
from cemaf.docs_api import build_default_index, CemafDocsSearchTool, DocsRetrievalTool

index = build_default_index()
tool_registry.register_instance(item=CemafDocsSearchTool(index=index))
tool_registry.register_instance(item=DocsRetrievalTool(index=index))
```

```bash
# MCP clients (Claude Desktop, IDE plugins) — run as stdio MCP server
uv run cemaf docs serve
```

In `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "cemaf-docs": {
      "command": "uv",
      "args": ["run", "cemaf", "docs", "serve"]
    }
  }
}
```

See [`src/cemaf/docs_api/`](src/cemaf/docs_api/) for the indexer, source
protocols, and search tools.

## Documentation

**[Full Documentation →](docs/README.md)**

### Start Here (new to CEMAF?)
- [**Architecture**](docs/architecture.md) - The software architecture we build toward
- [**Design Patterns**](docs/patterns.md) - Protocol-first, BYO-X, RuntimeServices, HaltSignal, Context-as-Patch
- [**Module Layout**](docs/modules.md) - Ideal package division, what lives where
- [Quick Start Guide](docs/quickstart.md) - Get running in 5 minutes

### Getting Started
- [Protocol Guide](docs/protocol_guide.md) - Understanding CEMAF's protocol-based architecture
- [Extension Patterns](docs/extension_patterns.md) - How to extend CEMAF with your own implementations
- [Standalone Usage](docs/standalone_usage.md) - Using modules independently

### Core Guides
- [Context Management](docs/context.md) - Patches, provenance, budgeting
- [Replay & Recording](docs/replay.md) - Deterministic replay
- [Tools, Skills, Agents](docs/tools.md) - Execution layer
- [Integration Guide](docs/integration.md) - Framework integration patterns

### Module References
- [LLM Integration](docs/llm.md)
- [Caching](docs/cache.md)
- [Persistence](docs/persistence.md)
- [Observability](docs/observability.md)
- [Citation Tracking](docs/citation.md) - Source attribution
- [MCP Integration](docs/mcp.md) - Model Context Protocol
- [Blueprint](docs/blueprint.md) - Semantic blueprints for content generation
- [Moderation](docs/moderation.md) - Guardrails and content safety
- [Retrieval](docs/retrieval.md) - Vector stores and search

---

## Configuration

CEMAF is designed for zero-config startup with production-ready defaults. Customize via environment variables:

```bash
# Copy example configuration
cp .env.example .env

# Configure your setup
CEMAF_LLM_PROVIDER=openai
CEMAF_LLM_API_KEY=your-key
CEMAF_CACHE_BACKEND=redis
CEMAF_CACHE_MAX_SIZE=10000
```

Use factory functions for automatic configuration loading:

```python
from cemaf.llm import create_llm_client_from_config
from cemaf.cache import create_cache_from_config

# Automatically loads from .env or environment
client = create_llm_client_from_config()
cache = create_cache_from_config()
```

See the [Configuration Guide](docs/config.md) for all available settings.

---

## Testing

```bash
# Run all tests
pytest tests/

# Unit tests only
pytest tests/unit/

# Skip slow tests
pytest tests/ -m "not slow"

# With coverage
pytest tests/ --cov=cemaf

# Pre-commit checks
pre-commit run --all-files
```

**Project Stats**: 2301+ tests | 100% passing | TDD from day one

---

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

Development setup:

```bash
# Fork and clone the repo
git clone https://github.com/YOUR_USERNAME/cemaf.git
cd cemaf

# Install dependencies with uv
uv venv
uv sync

# Install pre-commit hooks
uv run pre-commit install
```

See [HOW_TO_USE.md](HOW_TO_USE.md) for detailed usage examples.

---

## Getting Help

We're here to help! Here are the best ways to get support:

### Documentation

- [Full Documentation](docs/README.md) - Comprehensive guides for all features
- [Quick Start Guide](docs/quickstart.md) - Get started in minutes
- [HOW_TO_USE.md](HOW_TO_USE.md) - Detailed usage patterns
- [Architecture Guide](docs/architecture.md) - Understand CEMAF's design

### Community

- [Discord Server](https://discord.gg/C8ZXAbD8) - Join our community for real-time help
- [GitHub Discussions](https://github.com/drchinca/cemaf/discussions) - Ask questions and share ideas
- [GitHub Issues](https://github.com/drchinca/cemaf/issues) - Report bugs or request features

### Contributing

Want to contribute? Check out our [Contributing Guide](CONTRIBUTING.md) to get started!

We're in **Alpha** and actively seeking feedback!

---

## Philosophy & Open Startup

CEMAF operates as an **open startup** - we believe in radical transparency, community collaboration, and building in public.

### Our Principles

- **Community First:** We serve developers building AI agents
- **Transparent:** All decisions, metrics, and roadmap are public
- **Bias Toward Action:** Show > tell. Open PRs, not long debates
- **Anyone Can Help:** Contribution > credentials
- **Learn in Public:** We share wins AND mistakes

### Resources

- **[Philosophy Guide](docs/philosophy.md)** - Our 10 core principles and values
- **[Open Metrics](OPEN.md)** - Transparent metrics, roadmap, and financials
- **[Decision Log](docs/decisions/)** - All major decisions documented
- **[Weekly Updates](https://github.com/drchinca/cemaf/discussions)** - Progress, learnings, and challenges

**We're building CEMAF together. Your voice matters.**

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## Authors

**Hikuri Bado Chinca** ([@drchinca](https://github.com/drchinca))
Email: chincadr@gmail.com

Copyright (c) 2026 | Published on 1.1.2026 🎉

---

## Links

- **Documentation**: [docs/README.md](docs/README.md)
- **Issues**: [GitHub Issues](https://github.com/drchinca/cemaf/issues)
- **Contributing**: [CONTRIBUTING.md](CONTRIBUTING.md)
