# CEMAF

**Context Engineering Multi-Agent Framework**

A modular, pluggable framework for building multi-agent AI systems with dynamic DAG orchestration, context management, and memory persistence.

## 📚 Documentation

**👉 [Full Documentation](docs/README.md)**

- [Quick Start Guide](docs/quickstart.md)
- [Architecture Overview](docs/architecture.md)
- [Core Concepts](docs/core.md)
- [Orchestration](docs/orchestration.md)
- [Context Management](docs/context.md)
- [Tools, Skills, Agents](docs/tools.md)
- And [more...](docs/README.md)

## Installation

```bash
# Core only (no AI framework dependencies)
pip install cemaf

# With specific integrations
pip install cemaf[openai]      # OpenAI + tiktoken
pip install cemaf[anthropic]   # Anthropic
pip install cemaf[tiktoken]    # Accurate token counting only
pip install cemaf[all]         # All integrations

# Development
pip install cemaf[dev]
```

## Quick Example

```python
from cemaf.orchestration.dag import DAG, Node, Edge
from cemaf.core.types import NodeID
from cemaf.context.context import Context
from cemaf.orchestration.executor import DAGExecutor

# Build DAG
dag = DAG(name="pipeline")
dag = dag.add_node(Node.tool(id="search", name="Search", tool_id="search"))
dag = dag.add_node(Node.tool(id="summarize", name="Summarize", tool_id="summarize"))
dag = dag.add_edge(Edge(source=NodeID("search"), target=NodeID("summarize")))

# Visualize
dag.print_mermaid()

# Execute
executor = DAGExecutor(node_executor=my_executor)
result = await executor.run(dag, initial_context=Context(data={"query": "test"}))
```

## Key Features

- **🔧 Tools**: Atomic, stateless functions
- **⚡ Skills**: Composable capabilities
- **🤖 Agents**: Autonomous entities with goals
- **📊 DAGs**: Dynamic workflow orchestration with visualization
- **💾 Context**: Immutable context management with token budgeting
- **🧠 Memory**: Scoped memory persistence
- **🔄 Pluggable**: Protocol-based architecture for maximum flexibility

## Project Stats

- **426 tests** | **55 fixtures** | **TDD from day one**
- **MIT License**

## Testing

```bash
pytest tests/                    # all tests
pytest tests/unit/               # unit only
pytest tests/ -m "not slow"      # skip slow tests
pytest tests/ --cov=cemaf        # with coverage
```
