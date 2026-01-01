# CEMAF

**Context Engineering Multi-Agent Framework**

Context engineering infrastructure that solves the hard problems in AI agent systems. CEMAF can be used standalone OR plugged into existing frameworks like LangGraph, AutoGen, and CrewAI.

## Installation

```bash
# Minimal installation (core only)
pip install cemaf

# With optional dependencies
pip install "cemaf[tiktoken]"      # Accurate token counting
pip install "cemaf[openai]"        # OpenAI integration
pip install "cemaf[anthropic]"    # Anthropic integration
pip install "cemaf[all]"           # All optional dependencies

# Development installation
pip install -e ".[dev]"
```

**Python 3.14+ required**

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
- **⚙️ Configuration-Driven**: Zero-config defaults with .env customization

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

Use factories for automatic configuration loading:

```python
from cemaf.llm import create_llm_client_from_config
from cemaf.cache import create_cache_from_config

# Automatically loads from .env or environment
client = create_llm_client_from_config()
cache = create_cache_from_config()
```

See [Configuration Guide](docs/config.md) for all available settings.

## Project Stats

- **814 tests** | **100% passing** | **TDD from day one**
- **Python 3.14+** | **Fully typed** | **Protocol-based design**
- **MIT License**

## Testing

```bash
pytest tests/                    # all tests
pytest tests/unit/               # unit only
pytest tests/ -m "not slow"      # skip slow tests
pytest tests/ --cov=cemaf        # with coverage
```
