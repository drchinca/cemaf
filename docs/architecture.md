# Architecture Overview

CEMAF is built on a modular, pluggable architecture where all components are defined as `Protocol`s for dependency injection.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        ORCHESTRATION                            │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐  │
│  │ DeepAgent   │    │ DAGExecutor │    │ Checkpointer        │  │
│  │ Orchestrator│───▶│             │───▶│ (state persistence) │  │
│  └─────────────┘    └─────────────┘    └─────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
         │                    │
         ▼                    ▼
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│     AGENTS      │   │     SKILLS      │   │     TOOLS       │
│  (goals,state)  │──▶│  (composable)   │──▶│   (atomic)      │
└─────────────────┘   └─────────────────┘   └─────────────────┘
         │                    │                     │
         └────────────────────┴─────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│     CONTEXT     │   │     MEMORY      │   │       LLM       │
│  TokenBudget    │   │  Short/Long     │   │  Protocols      │
│  Compiler       │   │  Scoped         │   │  Streaming      │
└─────────────────┘   └─────────────────┘   └─────────────────┘
         │                    │                     │
         └────────────────────┴─────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│   PERSISTENCE   │   │   RETRIEVAL     │   │  OBSERVABILITY  │
│  Entities       │   │  VectorStore    │   │  Logger/Tracer  │
│  Protocols      │   │  Embeddings     │   │  Metrics        │
└─────────────────┘   └─────────────────┘   └─────────────────┘
```

## Core Concepts

### Tool → Skill → Agent Hierarchy

```
Tool     Atomic, stateless function (e.g., web_search, calculate)
  │
  ▼
Skill    Composable capability using tools (e.g., research, summarize)
  │
  ▼
Agent    Autonomous entity with goals, memory, decision-making
```

### Dynamic DAG Execution

```
        ┌───┐
        │ A │  Entry
        └─┬─┘
     ┌────┴────┐
     ▼         ▼
   ┌───┐     ┌───┐
   │ B │     │ C │  Parallel
   └─┬─┘     └─┬─┘
     │  ┌──┐  │
     └──▶D◀──┘     Convergence
        └─┬─┘
          ▼
       [output]
```

## Pluggability

All components are defined as `Protocol`s for dependency injection:

```python
# Swap implementations without changing code
executor = DAGExecutor(
    node_executor=my_executor,
    checkpointer=RedisCheckpointer(),  # or InMemoryCheckpointer()
)

memory = PostgresMemoryStore()  # or InMemoryStore()
llm = AnthropicClient()         # or OpenAIClient(), MockLLMClient()
```

## Project Structure

```
cemaf/
├── src/cemaf/
│   ├── core/           # Types, enums, constants, Result, InMemoryStorage, utils
│   ├── tools/          # Tool abstractions
│   ├── skills/         # Skill abstractions
│   ├── agents/         # Agent abstractions
│   ├── orchestration/  # DAG, Executor, DeepAgent
│   ├── context/        # TokenBudget, Compiler, Context, AdvancedContextCompiler
│   ├── memory/         # MemoryStore protocols
│   ├── persistence/    # Entities (Project, Run, Artifact)
│   ├── llm/            # LLM client protocols
│   ├── retrieval/      # VectorStore, Embeddings
│   ├── streaming/      # SSE, StreamBuffer
│   ├── generation/     # Image, Audio, Video, UI, Code generation
│   ├── evals/          # Evaluators, LLM-as-judge
│   ├── resilience/     # Retry, CircuitBreaker, RateLimiter
│   ├── observability/  # Logger, Tracer, Metrics
│   ├── scheduler/      # Job scheduling, triggers
│   ├── validation/   # Validation rules and pipelines
│   ├── events/         # Event bus and notifiers
│   ├── cache/          # Caching with TTL and eviction
│   └── config/         # Configuration management
└── tests/
    ├── conftest.py     # 55 reusable fixtures
    ├── unit/
    └── integration/
```

## Design Principles

1. **Protocol-Based**: All components use Python `Protocol`s for maximum flexibility
2. **Immutable Context**: State is managed through immutable `Context` objects
3. **Result Pattern**: All operations return `Result[T]` for explicit error handling
4. **Testability**: Comprehensive test suite with 426 tests and 55 fixtures
5. **Modularity**: Each module is independent and can be used standalone

