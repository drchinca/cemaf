# CEMAF Documentation

Context Engineering Multi-Agent Framework

## Quick Links

- [Quick Start](quickstart.md) - Get running in 5 minutes
- [Architecture](architecture.md) - System design overview
- [Module Reference](module_reference.md) - API reference

---

## Documentation by Mental Model

### 1. Context Engineering (The Core)

CEMAF's differentiator: industrial-grade context management.

| Doc | Purpose |
|-----|---------|
| [context.md](context.md) | Immutable Context object, patches, provenance |
| [context_algorithms.md](context_algorithms.md) | Selection algorithms, KV cache, semantic compression |
| [ingestion.md](ingestion.md) | Context adapters - format/compress/prioritize data |

**Key Question**: "How do I fit relevant information into the token budget?"

### 2. Orchestration (The Engine)

DAG-based execution with parallel branches and conditional routing.

| Doc | Purpose |
|-----|---------|
| [orchestration.md](orchestration.md) | DAG definition, Node types, execution flow |
| [tools.md](tools.md) | Tool protocol, registration, execution |
| [skills.md](skills.md) | Multi-tool compositions |
| [agents.md](agents.md) | Full agent implementations |

**Key Question**: "How do I coordinate multiple operations?"

### 3. Edge Capabilities (The Differentiator)

Run agents on resource-constrained, intermittently-connected devices.

| Doc | Purpose |
|-----|---------|
| [offline.md](offline.md) | Store-and-forward, offline queues, local LLM fallback |
| [throttling.md](throttling.md) | Resource guards, circuit breakers, context paging |
| [sync.md](sync.md) | State synchronization, CRDT, conflict resolution |

**Key Question**: "How do I run reliably on a Raspberry Pi with spotty WiFi?"

### 4. Observability (The Debugger)

Understand what your agent did and why.

| Doc | Purpose |
|-----|---------|
| [observability.md](observability.md) | RunLogger, metrics, tracing |
| [replay.md](replay.md) | Deterministic replay from RunRecords |
| [evals.md](evals.md) | Agent evaluation framework |

**Key Question**: "Why did the agent do that?"

### 5. Infrastructure (The Plumbing)

Supporting systems for production deployments.

| Doc | Purpose |
|-----|---------|
| [resilience.md](resilience.md) | Retry, circuit breaker, rate limiting |
| [events.md](events.md) | Event bus, pub/sub |
| [memory.md](memory.md) | Memory stores, TTL, scopes |
| [persistence.md](persistence.md) | Entity storage, versioning |
| [cache.md](cache.md) | Caching strategies |
| [scheduler.md](scheduler.md) | Task scheduling |

**Key Question**: "How do I run this in production?"

### 6. Integration (The Glue)

Connect CEMAF to external systems.

| Doc | Purpose |
|-----|---------|
| [llm.md](llm.md) | LLM client protocols, providers |
| [integration.md](integration.md) | Framework integration patterns |
| [streaming.md](streaming.md) | Streaming responses |
| [generation.md](generation.md) | Content generation |
| [validation.md](validation.md) | Input/output validation |

**Key Question**: "How do I connect to X?"

### 7. Configuration (The Setup)

Configure CEMAF for your environment.

| Doc | Purpose |
|-----|---------|
| [config.md](config.md) | Configuration system |
| [env_configuration.md](env_configuration.md) | Environment variables |
| [vector_store_config.md](vector_store_config.md) | Vector store setup |

**Key Question**: "How do I configure this?"

---

## Architecture Principles

### 1. Protocol-First Design

Every component is defined by a Protocol. Swap implementations freely.

```python
# Your custom implementation works everywhere
class MyTokenEstimator(TokenEstimator):
    def estimate(self, text: str) -> int:
        return len(tiktoken.encode(text))

compiler = create_priority_compiler(token_estimator=MyTokenEstimator())
```

### 2. Immutable State

Context is immutable. Every change returns a new Context with full provenance.

```python
ctx1 = Context(data={"count": 1})
ctx2 = ctx1.set("count", 2)  # ctx1 unchanged
# Rollback = just use ctx1
```

### 3. DI-Friendly Factories

All factories accept explicit dependencies for testing.

```python
# Testing
compiler = create_priority_compiler(
    token_estimator=MockEstimator(),
    algorithm=MockAlgorithm(),
)

# Production (from environment)
compiler = create_context_compiler_from_config()
```

### 4. Edge-Native

Every feature considers resource constraints and intermittent connectivity.

---

## Mode A vs Mode B

### Mode A: Orchestrator

Use CEMAF's full DAG execution engine.

```python
from cemaf.orchestration import DAG, DAGExecutor

dag = DAG("my_agent")
dag = dag.add_node(Node.tool("search", ...))
dag = dag.add_node(Node.tool("analyze", ...))
result = await executor.run(dag, context)
```

### Mode B: Library

Use individual CEMAF modules in your existing framework.

```python
# Just use context compilation in LangChain
from cemaf.context import PriorityContextCompiler

compiler = PriorityContextCompiler()
compiled = await compiler.compile(sources, budget)

# Pass to your existing chain
response = my_langchain_chain.run(compiled.to_text())
```

---

## Next Steps

1. **New to CEMAF?** Start with [Quick Start](quickstart.md)
2. **Integrating with existing code?** See [Integration](integration.md)
3. **Deploying to edge?** Read [Offline](offline.md), [Throttling](throttling.md), [Sync](sync.md)
4. **Understanding context management?** Deep dive into [Context Algorithms](context_algorithms.md)
