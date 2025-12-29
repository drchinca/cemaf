# CEMAF

**Context Engineering Multi-Agent Framework**

Context engineering infrastructure that solves the hard problems in AI agent systems. CEMAF can be used standalone OR plugged into existing frameworks like LangGraph, AutoGen, and CrewAI.

## The Hard Problems We Solve

| Problem | What Happens | CEMAF Solution |
|---------|--------------|----------------|
| **Context Growth** | Token limits blow up | Token budgeting + automatic summarization |
| **Reliability** | Non-deterministic behavior | Patch-based provenance tracking |
| **Cost** | Wasteful token usage | Smart context compilation |
| **Reproducibility** | Can't replay/debug runs | Run recording + deterministic replay |
| **Memory Leaks** | State bleeds between scopes | Strict memory boundaries with TTL |

## Two Integration Modes

### Mode A: CEMAF Orchestrates
CEMAF owns execution, external frameworks are "engines":

```python
from cemaf.orchestration import DAGExecutor
from cemaf.observability import InMemoryRunLogger

executor = DAGExecutor(
    node_executor=LangGraphNodeExecutor(langgraph_app),
    run_logger=InMemoryRunLogger(),  # Full recording
)
result = await executor.run(dag, context)

# Replay later for debugging
replayer = Replayer(run_logger.get_record("run-123"))
await replayer.replay()
```

### Mode B: CEMAF as Library
External frameworks orchestrate, CEMAF provides infrastructure:

```python
from cemaf.context import Context, ContextPatch, PatchSource
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

## Documentation

**[Full Documentation](docs/README.md)**

- [Quick Start Guide](docs/quickstart.md)
- [Architecture Overview](docs/architecture.md)
- [Context Management](docs/context.md) - Patches, provenance, budgeting
- [Replay & Recording](docs/replay.md) - Deterministic replay
- [Integration Guide](docs/integration.md) - Mode A/B patterns
- [Tools, Skills, Agents](docs/tools.md)

## Installation

```bash
# Core only (no AI framework dependencies)
pip install cemaf

# With specific integrations
pip install cemaf[openai]      # OpenAI + tiktoken
pip install cemaf[anthropic]   # Anthropic
pip install cemaf[tiktoken]    # Accurate token counting only
pip install cemaf[all]         # All integrations
```

## Quick Example

```python
from cemaf.context import Context, ContextPatch, PatchLog
from cemaf.observability import InMemoryRunLogger
from cemaf.replay import Replayer

# Create context with provenance tracking
ctx = Context()
patch = ContextPatch.from_tool("search", "results", {"items": [...]})
ctx = ctx.apply(patch)

# Record runs for replay
logger = InMemoryRunLogger()
logger.start_run("run-123", initial_context=ctx)
logger.record_patch(patch)
record = logger.end_run(final_context=ctx)

# Replay deterministically
replayer = Replayer(record)
result = await replayer.replay()
assert result.final_context == record.final_context  # Deterministic!
```

## Key Features

- **📍 Context Patches**: Track every context change with full provenance
- **🔄 Deterministic Replay**: Record and replay runs for debugging
- **💾 Token Budgeting**: Stay within limits with smart compilation
- **⏱️ TTL & Cleanup**: Memory items expire automatically
- **🔒 Memory Boundaries**: Strict scoping prevents state leaks
- **⚡ Cancellation**: Cooperative cancellation with timeouts
- **🔧 Protocol-Based**: Plug into any framework

## Project Stats

- **519 tests** | **55 fixtures** | **TDD from day one**
- **MIT License**

## Testing

```bash
pytest tests/                    # all tests
pytest tests/unit/               # unit only
pytest tests/ -m "not slow"      # skip slow tests
pytest tests/ --cov=cemaf        # with coverage
```
