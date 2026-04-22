# CEMAF

**Context Engineering Multi-Agent Framework**

[![Open Source](https://img.shields.io/badge/Open%20Source-%E2%9D%A4-red?style=flat-square)](https://opensource.org)
[![Project Status: Alpha](https://img.shields.io/badge/Status-Alpha-yellow?style=flat-square)](https://github.com/drchinca/cemaf)
[![Discord](https://img.shields.io/badge/Discord-Join_Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/C8ZXAbD8)
[![Python](https://img.shields.io/badge/Python-3.14+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/Tests-2700+_Passing-success?style=flat-square&logo=pytest&logoColor=white)](.)
[![Coverage](https://img.shields.io/badge/Coverage-80%25-brightgreen?style=flat-square)](.)
[![CI](https://img.shields.io/github/actions/workflow/status/drchinca/cemaf/ci.yml?branch=main&style=flat-square&logo=github&label=CI)](https://github.com/drchinca/cemaf/actions/workflows/ci.yml)
[![Ruff](https://img.shields.io/badge/Code_Style-Ruff-FCC21B?style=flat-square&logo=ruff&logoColor=black)](https://github.com/astral-sh/ruff)
[![MyPy](https://img.shields.io/badge/Typed-MyPy-blue?style=flat-square)](http://mypy-lang.org/)
[![Stars](https://img.shields.io/github/stars/drchinca/cemaf?style=flat-square&logo=github)](https://github.com/drchinca/cemaf)
[![Issues](https://img.shields.io/github/issues/drchinca/cemaf?style=flat-square&logo=github)](https://github.com/drchinca/cemaf/issues)
[![Open Startup](https://img.shields.io/badge/Open-Startup-00ADD8?style=flat-square)](OPEN.md)

**Open source** context engineering infrastructure that solves the hard problems in AI agent systems. CEMAF can be used standalone or plugged into existing frameworks like LangGraph, AutoGen, and CrewAI.

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

**Read [docs/architecture.md](docs/architecture.md)** for the canonical software architecture we build toward, **[docs/patterns.md](docs/patterns.md)** for the design patterns catalog, and **[docs/modules.md](docs/modules.md)** for ideal package boundaries.

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
pip install -e ".[dev]"
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

---

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
