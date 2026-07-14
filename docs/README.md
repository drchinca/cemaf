# CEMAF Documentation

**Context Engineering Multi-Agent Framework**

Protocol-first framework for running multi-agent LLM workloads with provenance, budget control, eval, moderation, and self-hosting. Use standalone or drop modules into LangGraph / AutoGen / CrewAI.

---

## Start here

New to CEMAF? Read these three in order:

1. **[Architecture](architecture.md)** — the software architecture we build toward. Layer 1 / Layer 2, dependency invariants, composition root, what we say no to.
2. **[Design Patterns](patterns.md)** — the 12 patterns that show up everywhere. Protocol-first, BYO-X, RuntimeServices, HaltSignal, immutable-context-patches, ContextVar per-run, decorator LLM clients.
3. **[Module Layout](modules.md)** — where each kind of thing lives. When you're unsure where a new file goes, check here.

Then pick your entry point:
- Want to build something: [Quick Start](quickstart.md)
- Using an AI coding assistant: [Agent-Assisted Development](agent-assisted-development.md)
- Want to extend CEMAF: [Extension Patterns](extension_patterns.md)
- Want to integrate with your framework: [Integration Guide](integration.md)

---

## How CEMAF is structured

```
┌───────────────────────────────────────────────────────────────────┐
│  LAYER 2 — Self-Hosting                                            │
│  audit/ ◄── knowledge/ ◄── meta/ (Specifier, Architect, …)        │
│                                                                    │
│  ─── one-way dependency ────────────────────────────────────────   │
│                                                                    │
│  LAYER 1 — Base Framework                                          │
│                                                                    │
│    orchestration/ ──► DAGExecutor, RuntimeServices, node handlers │
│         │                                                          │
│         ▼                                                          │
│    agents/ • tools/ • skills/ • blueprint/                         │
│    context/ • memory/ • retrieval/ • rlm/                         │
│    llm/ • generation/ • streaming/                                 │
│    evals/ • moderation/ • validation/ • citation/                 │
│    events/ • observability/ • resilience/ • persistence/          │
│    mcp/ • cache/ • replay/ • ingestion/                           │
│                                                                    │
│    Composition root:                                               │
│      bootstrap.create_executor(                                    │
│          agent_registry,                                           │
│          services=RuntimeServices(...),                            │
│          config=ExecutorConfig(...),                               │
│      )                                                             │
└───────────────────────────────────────────────────────────────────┘
```

Full diagram + per-module details: [modules.md](modules.md).

---

## Documentation index

### Getting Started
- [Quick Start](quickstart.md) — install, run, first agent
- [Agent-Assisted Development](agent-assisted-development.md) — CEMAF-first checklist for LLM/coding-agent integrations
- [Documentation Voice](writing_style.md) — direct public-docs tone, no launch-copy language
- [AI Integration & Development Guide](AI_DEVELOPMENT_GUIDE.md) — Dense reference of code recipes, standards, and guardrails for AIs
- [Protocol Guide](protocol_guide.md) — how the protocol layer works
- [Extension Patterns](extension_patterns.md) — BYO-LLM, BYO-VectorStore, BYO-MemoryBackend
- [Standalone Usage](standalone_usage.md) — using modules independently
- [Integration Guide](integration.md) — Mode A (CEMAF orchestrates) and Mode B (CEMAF as library)

### Canonical reference (read these)
- [**Architecture**](architecture.md) — the software architecture we build toward
- [**Industry-Standard Goals**](architecture/industry-standard-goals.md) — the eight product pillars and evidence required for huge-context autonomous work
- [**Capability Evidence Ledger**](production-evidence.md) — executable proof and explicit limits for every current public capability claim
- [**Enterprise Durability Plan**](architecture/enterprise-durability-plan.md) — authoritative runtime state, backend roles, migration, verification, and rollout
- [**Durable Execution Injection Boundary**](architecture/durable-execution-injection-decision.md) — what is injected, what the companion owns, and how abandoned work is recovered
- [**Design Patterns**](patterns.md) — the pattern catalog reviewers enforce
- [**Module Layout**](modules.md) — where each thing lives

### Context Engineering (core differentiator)
- [Context Management](context.md) — Context, ContextPatch, ContextCompiler, TokenBudget
- [Replay & Recording](replay.md) — RunLogger, RunRecord, deterministic replay
- [Memory](memory.md) — MemoryManager, scopes, TTL, tiered storage, sessions

### Execution Layer
- [Tools](tools.md) — atomic, stateless functions with recording
- [Skills](skills.md) — composable capabilities
- [Agents](agents.md) — autonomous entities with typed goals/results
- [Orchestration](orchestration.md) — DAG, Executor, Node handlers, Checkpointing

### Quality & Safety
- [Evals](evals.md) — evaluators, hierarchical judge, online eval pipeline, quality police, groundedness
- [Moderation](moderation.md) — pre/post-flight gates, PII, ModeratingLLMClient, streaming moderation
- [Validation](validation.md) — contract-shape validation
- [Citation](citation.md) — source tracking and verification

### LLM Integration
- [LLM](llm.md) — LLMClient protocol, provider adapters, decorators (moderating, resilient, instrumented), exact token counting

### Observability
- [Observability](observability.md) — structured logger, Prometheus metrics, RunLogger, BudgetGuard, HealthMonitor, glass-box audit
- [Provenance](core.md#provenance) — ProvenanceChain linking LLM calls to context sources

### Infrastructure
- [Core](core.md) — types, enums, Result[T], IDs, utilities
- [Resilience](resilience.md) — RetryPolicy, CircuitBreaker, RateLimiter
- [Events](events.md) — EventBus pub/sub
- [Persistence](persistence.md) — Project, RunRecord, durable storage
- [Cache](cache.md) — TTL caching
- [Config](config.md) — Settings, env loading, provider registry
- [Scheduler](scheduler.md) — gates and task scheduling

### Integrations
- [MCP](mcp.md) — Model Context Protocol adapter + OpenSpec bridge
- [Retrieval](retrieval.md) — VectorStore, EmbeddingProvider protocols
- [Blueprint](blueprint.md) — semantic blueprints for structured generation
- [Streaming](streaming.md) — SSE, stream buffers
- [Generation](generation.md) — image, audio, video, UI, code
- [RLM](rlm.md) — Recursive LLM for 1M+ token contexts

### Self-Hosting (Layer 2)
- [Self-Hosting Layer](self-hosting.md) — the whole Layer 2: meta-agents, meta-tools, and the pre-built meta-DAGs
- [Audit & anomaly detection](self-hosting.md#self_audit) — the `self_audit` meta-DAG over AuditTrail
- [Knowledge refresh](self-hosting.md#knowledge_refresh) — entities + relations backed by memory

### Analysis Notes
- [Graph Backend Seams For CEMAF](analysis/GRAPH_BACKEND_SEAMS_FOR_CEMAF.md) — graph database adapter boundaries, branchable KG contracts, and what CEMAF should not reimplement

---

## Quick links

| Task | Doc |
|------|------|
| Wire up a full executor | [architecture.md § composition root](architecture.md#composition-root) |
| Plug in your own LLM | [patterns.md § BYO-X](patterns.md#2-bring-your-own-x-byo-x) |
| Halt a runaway DAG | [patterns.md § HaltSignal](patterns.md#8-haltsignal-with-structured-reason) |
| Get exact token counts | [llm.md § count_tokens_exact](llm.md) |
| Detect prompt injection via tools | [moderation.md § ModeratingLLMClient](moderation.md) |
| Track what the LLM saw | [context.md § patches](context.md) |
| Run recorded executions | [replay.md](replay.md) |
| Build self-specifying apps | [self-hosting.md § feature_synthesis](self-hosting.md#feature_synthesis) |
| Add a new cross-cutting controller | [modules.md § placement decisions](modules.md#placement-decisions--worked-examples) |

---

## Project stats

- **Comprehensive test suite** (unit + integration) | **100% passing** | TDD from day one
- **Python 3.14+** | fully typed | protocol-based design
- Glass-box audit | provenance tracking | budget enforcement | structured halt signals
- Multiple LLM provider backends supported out-of-box; exact token counting via provider APIs
- MIT License
