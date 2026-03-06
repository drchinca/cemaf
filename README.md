# CEMAF

**Context Engineering Multi-Agent Framework**

[![Open Source](https://img.shields.io/badge/Open%20Source-%E2%9D%A4-red?style=flat-square)](https://opensource.org)
[![Project Status: Alpha](https://img.shields.io/badge/Status-Alpha-yellow?style=flat-square)](https://github.com/drchinca/cemaf)
[![Discord](https://img.shields.io/badge/Discord-Join_Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/C8ZXAbD8)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/Tests-1464_Passing-success?style=flat-square&logo=pytest&logoColor=white)](.)
[![Coverage](https://img.shields.io/badge/Coverage-77%25-yellow?style=flat-square)](.)
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

CEMAF is a protocol-first framework designed for **context engineering** in multi-agent AI systems. It provides:

- Token budgeting and automatic context optimization
- Deterministic run recording and replay capabilities
- Full provenance tracking for every context change
- Memory management with strict scoping and TTL
- Zero-config defaults with environment-based customization

**Philosophy**: Own the hard infrastructure problems while remaining framework-agnostic.

**Design**: Protocol-based architecture where modules work standalone. Use our defaults or replace them with your own implementations. See [Protocol Guide](docs/protocol_guide.md) for details.

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
| **Prompt Engineering** | Inconsistent LLM outputs | Semantic blueprints for structured content generation |

---

## Installation

```bash
# Core installation (minimal dependencies)
pip install cemaf

# With optional integrations
pip install "cemaf[openai]"        # OpenAI + tiktoken
pip install "cemaf[anthropic]"    # Anthropic
pip install "cemaf[tiktoken]"     # Accurate token counting only
pip install "cemaf[all]"          # All optional dependencies

# Development installation
git clone https://github.com/drchinca/cemaf.git
cd cemaf
pip install -e ".[dev]"
```

**Requirements**: Python 3.11+

---

## Quick Start

```python
from cemaf.context import Context, ContextPatch
from cemaf.observability import InMemoryRunLogger
from cemaf.replay import Replayer
from cemaf.blueprint import Blueprint, SceneGoal, StyleGuide
from cemaf.moderation import ModerationPipeline, PreFlightGate, KeywordRule, PIIRule

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

# Use semantic blueprints for structured content generation
blueprint = Blueprint(
    id="social-post",
    name="Social Media Post",
    scene_goal=SceneGoal(objective="Create engaging social media content"),
    style_guide=StyleGuide(tone="casual", length_hint="concise")
)
prompt = blueprint.to_prompt()  # Convert to LLM-ready prompt

# Add content safety with moderation guardrails
moderation = ModerationPipeline(
    pre_flight=PreFlightGate([KeywordRule(["spam", "scam"]), PIIRule()])
)
result = await moderation.check_input(user_message)
if not result.allowed:
    raise ValueError(f"Content blocked: {result.violations}")
```

See the [Quick Start Guide](docs/quickstart.md) for more detailed examples.

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

- **📍 Context Patches**: Track every context change with full provenance
- **🔄 Deterministic Replay**: Record and replay runs for debugging
- **💾 Token Budgeting**: Stay within limits with smart compilation
- **⏱️ TTL & Cleanup**: Memory items expire automatically
- **🔒 Memory Boundaries**: Strict scoping prevents state leaks
- **⚡ Cancellation**: Cooperative cancellation with timeouts, integrated into DAGExecutor
- **🔧 Protocol-Based**: Plug into any framework - modules work standalone, extend with your own implementations
- **🔌 Extensible Registries**: ProviderRegistry pattern for pluggable LLM, compiler, and retrieval backends
- **🔁 Loop Nodes**: Iterative subgraph execution with exit conditions and max iterations
- **📡 Instrumented LLM**: Transparent LLM call recording for automatic glass box audit
- **⚙️ Configuration-Driven**: Zero-config defaults with .env customization
- **📋 Semantic Blueprints**: Structured content generation with Denis Rothman's blueprint pattern
- **🛡️ Moderation & Guardrails**: Pre/post-flight content safety with PII detection and compliance rules
- **🔍 Glass Box Audit**: Full provenance chain linking every LLM call to its context sources, citations, and costs
- **💰 Budget Guard**: Configurable cost and token limits with warning/critical/halt thresholds across DAG runs
- **🤖 Context Agents**: Built-in Librarian, Researcher, Summarizer, Writer agents with dynamic registry
- **♾️ Recursive LLM**: Parallel divide-and-conquer querying for 1M+ token contexts

---

## Documentation

**[Full Documentation →](docs/README.md)**

### Getting Started
- [Quick Start Guide](docs/quickstart.md) - Get running in 5 minutes
- [Protocol Guide](docs/protocol_guide.md) - Understanding CEMAF's protocol-based architecture
- [Extension Patterns](docs/extension_patterns.md) - How to extend CEMAF with your own implementations
- [Standalone Usage](docs/standalone_usage.md) - Using modules independently

### Core Guides
- [Architecture Overview](docs/architecture.md) - System design and principles
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

**Project Stats**: 1464 tests | 100% passing | TDD from day one

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
