# How to Use CEMAF

**Context Engineering Multi-Agent Framework**

This guide explains how to use CEMAF in your projects. CEMAF provides **context engineering infrastructure** that can work standalone or integrate with existing agent frameworks.

---

## Philosophy: Foundational Guidance, Not Batteries-Included

**CEMAF is infrastructure for engineers who build AI systems, not a complete framework.**

### What CEMAF Is

CEMAF is **foundational guidance** on how to do context engineering right. Think of it as:

- 📚 **Reference implementations** showing best practices
- 🏗️ **Extensible patterns** you can fork, modify, and build upon
- 🎓 **Teaching materials** embodying context engineering principles
- 🔧 **Core infrastructure** solving hard problems (token budgeting, provenance, replay)

**Not:** A batteries-included framework like LangChain or LangGraph
**But:** The foundational layer they could be built on

### How Engineers Use CEMAF

```python
# CEMAF shows you THE pattern
from cemaf.llm import ResponseParser

# You extend it for YOUR needs
class XMLResponseParser(ResponseParser):
    """Parse XML instead of JSON - same pattern"""

class ProtoResponseParser(ResponseParser):
    """Parse Protocol Buffers - same pattern"""
```

**You're meant to:**
- ✅ Fork the patterns for your use case
- ✅ Extend the classes with domain-specific logic
- ✅ Learn the principles and apply them
- ✅ Use what you need, ignore what you don't

**You're not meant to:**
- ❌ Use CEMAF as a black box
- ❌ Wait for CEMAF to add every feature you need
- ❌ Think "CEMAF doesn't do X, so I can't use it"

### The Principles We Teach

Every module in CEMAF embodies core principles:

#### 1. **Immutability** (Context never mutates)
```python
@dataclass(frozen=True)  # Everything is frozen
class ContextSource: ...
class ParseResult: ...

# Never: ctx.set_value(key, value)
# Always: new_ctx = ctx.set(key, value)
```

#### 2. **Provenance Tracking** (Know where every change came from)
```python
patch = ContextPatch.from_tool(
    tool_id="web_search",
    path="results",
    value=data,
)
ctx = ctx.apply(patch)  # Full audit trail
```

#### 3. **Protocol-First Design** (Not tied to implementations)
```python
# Works with ANY implementation
def compile(compiler: ContextCompiler, ...):
    # Don't care what kind of compiler
```

#### 4. **Progressive Disclosure** (Simple → Advanced)
```python
# Level 1: Dead simple
result = ResponseParser.parse_json(text)

# Level 2: With validation
result = ResponseParser.parse_to_model(text, UserProfile)

# Level 3: Streaming
parser = StreamingJSONParser()
```

### Real-World Example: How Teams Extended CEMAF

**KYI Team** (Instagram analysis):
```python
# Started with CEMAF's Context + Patches
from cemaf.context import Context, ContextPatch

# Extended with domain logic
class InstagramPostSource(ContextSource):
    """Their extension - posts with engagement scores"""
    likes: int
    comments: int
    engagement_rate: float
```

**Warehouse RAG Team** (SQL agent):
```python
# Used CEMAF's patterns
from cemaf.context import ContextCompiler

# Built LangChain bridge (375 lines)
class LangChainCEMAFBridge:
    """Connected LangChain to CEMAF patterns"""
    # Now we provide this officially in cemaf-integrations
```

**MeridianSight Team** (Content generation):
```python
# Adopted 3-level memory pattern
# Tenant → Project → Session scoping
from cemaf import MemoryScope

# Extended with social media logic
class SocialPostMemory(MemoryItem):
    platform: str
    scheduled_time: datetime
```

### What CEMAF Provides vs. What You Build

| CEMAF Provides | You Build |
|----------------|-----------|
| **ResponseParser** (JSON from LLMs) | XMLParser, ProtoParser for your formats |
| **ContextPath[T]** (type-safe paths) | Your domain-specific path schemas |
| **ContextSource** (metadata + priority) | Custom source types (VectorSource, StreamingSource) |
| **Token budgeting** (stay within limits) | Your compilation strategies (semantic chunking, etc.) |
| **Provenance tracking** (audit trail) | Your audit visualization/analytics |
| **Replay system** (deterministic runs) | Your debugging/monitoring tools |

### When to Use CEMAF

✅ **Use CEMAF when:**
- You're building production AI agents and need **foundational infrastructure**
- You want to **learn best practices** for context engineering
- You need **extensible patterns** you can customize
- You value **determinism, provenance, and reproducibility**

❌ **Don't use CEMAF when:**
- You want a **complete framework** with batteries included (use LangChain/LangGraph)
- You're building a **simple chatbot** that doesn't need infrastructure
- You want **zero code** - just configuration (CEMAF requires engineering)

### CEMAF vs. Other Frameworks

| Framework | Philosophy | When to Use |
|-----------|-----------|-------------|
| **LangChain** | Complete toolkit, opinionated | Need pre-built chains, quick prototypes |
| **LangGraph** | Stateful multi-actor apps | Need framework-managed state graphs |
| **CrewAI** | Role-based agent teams | Want high-level agent abstractions |
| **CEMAF** | **Foundational patterns for context engineering** | **Building production systems, need control** |

**CEMAF works WITH these frameworks** - see Mode A/B integration below.

### New in Phase 1: Reference Patterns

We've added **three reference implementations** showing CEMAF patterns:

#### 1. **response_utils.py** - LLM Response Handling Pattern

Shows how to:
- Parse JSON from markdown code blocks, inline, or raw
- Validate with Pydantic models
- Handle streaming responses
- Provide LLM-friendly error messages for retry loops

```python
from cemaf.llm import ResponseParser

# The CEMAF way: Multiple strategies with structured results
result = ResponseParser.parse_json(llm_response)
if result.success:
    data = result.data
else:
    # Error message designed for LLM to self-correct
    retry_with_feedback(result.error_message)
```

**Extend it:**
```python
class MyCustomParser(ResponseParser):
    @classmethod
    def parse_xml(cls, text: str) -> ParseResult[dict]:
        # Your logic, same pattern
```

#### 2. **paths.py** - Type-Safe Context Access Pattern

Shows how to:
- Add type safety without breaking existing code (wrapper pattern)
- Use generics for IDE autocomplete
- Build fluent APIs with builders

```python
from cemaf.context import ContextPath, TypedContext

# Define typed paths
class Paths:
    user_name = ContextPath[str]("user.name")
    scores = ContextPath[list[float]]("analysis.scores")

# Type-safe access with autocomplete
ctx = TypedContext(Context())
ctx = ctx.set(Paths.user_name, "Alice")  # IDE knows types!
```

**Extend it:**
```python
# Copy the pattern for your own types
class TypedMemory:
    """Same wrapper pattern for memory"""
    def get(self, path: MemoryPath[T]) -> T | None: ...
```

#### 3. **source.py** - Context Source Management Pattern

Shows how to:
- Model context sources with rich metadata
- Use priority + recency for intelligent selection
- Design factory methods for ergonomic APIs
- Enable token-aware compilation

```python
from cemaf.context import ContextSource

# Factory methods for common patterns
system = ContextSource.from_system_prompt("You are...", priority=100)
memory = ContextSource.from_memory("User likes...", priority=80)
doc = ContextSource.from_document("Reference...", priority=40)

# Automatic sorting by priority + timestamp
sources = sorted([doc, memory, system])
# → [system, memory, doc] - smart prioritization!
```

**Extend it:**
```python
class VectorContextSource(ContextSource):
    """Add vector similarity"""
    embedding: list[float]
    similarity_score: float

    @classmethod
    def from_vector_search(cls, ...): ...
```

### The CEMAF Development Cycle

```
1. Study CEMAF patterns
   ↓
2. Fork/extend for your needs
   ↓
3. Build domain logic on top
   ↓
4. Share improvements back (optional)
```

**Example:**
```python
# 1. Study: CEMAF shows ResponseParser pattern
from cemaf.llm import ResponseParser

# 2. Fork: You need YAML parsing
class YAMLResponseParser:
    """Same pattern, YAML instead of JSON"""
    @classmethod
    def parse_yaml(cls, text: str) -> ParseResult[dict]:
        # Your implementation

# 3. Build: Your domain logic
class AgentConfigParser(YAMLResponseParser):
    """Domain-specific: Parse agent configs from LLM"""
    @classmethod
    def parse_agent_config(cls, text: str) -> ParseResult[AgentConfig]:
        # Business logic
```

### Learning Resources

- **Code is Documentation**: Read the source - it's **teaching material**
- **Examples/**: Real-world patterns from production systems
- **Tests/**: Show how to use every feature
- **IMPROVEMENT_PLAN.md**: Roadmap of upcoming patterns

---

## Quick Start: Zero-Config Setup

CEMAF works out of the box with sensible defaults. For customization, copy the `.env.example`:

```bash
cp .env.example .env
# Edit .env with your API keys and preferences
```

**Recommended: Use factory functions** for automatic configuration loading:

```python
from cemaf.llm import create_llm_client_from_config
from cemaf.cache import create_cache_from_config
from cemaf.context import create_context_compiler_from_config

# All settings auto-loaded from .env (or use defaults)
llm = create_llm_client_from_config()
cache = create_cache_from_config()
compiler = create_context_compiler_from_config()
```

**Environment variable examples:**
```bash
# LLM Configuration
CEMAF_LLM_PROVIDER=openai
CEMAF_LLM_API_KEY=your-api-key
CEMAF_LLM_DEFAULT_MODEL=gpt-4o-mini

# Cache Configuration
CEMAF_CACHE_BACKEND=memory
CEMAF_CACHE_MAX_SIZE=1000
CEMAF_CACHE_DEFAULT_TTL_SECONDS=3600

# Memory Configuration
CEMAF_MEMORY_BACKEND=memory
CEMAF_MEMORY_DEFAULT_CONFIDENCE=0.8
```

For all configuration options, see [docs/config.md](docs/config.md) and `.env.example`.

---

## Quick Decision Tree

```
Do you have an existing agent system?
├─ No → Use Mode A (CEMAF Orchestrates)
└─ Yes → Use Mode B (CEMAF as Library)
    └─ Want to migrate? → Gradually adopt Mode A features
```

---

## Two Integration Modes

CEMAF supports two integration modes to fit different project needs:

| Mode | Who Orchestrates | Who Provides Infrastructure | Best For |
|------|------------------|------------------------------|----------|
| **Mode A** | CEMAF (DAGExecutor) | CEMAF | New projects, full control |
| **Mode B** | Your Framework (LangGraph/AutoGen/etc.) | CEMAF | Existing projects, gradual adoption |

---

## Mode A: CEMAF Orchestrates

**CEMAF owns the execution flow.** External frameworks (LangGraph, AutoGen, CrewAI) are used as "engines" for specific nodes.

### When to Use Mode A

✅ **Use Mode A if:**
- Starting a new project (greenfield)
- You want full CEMAF features (automatic replay, provenance tracking)
- You need CEMAF's advanced DAG features (parallel execution, routing, checkpointing)
- You want CEMAF to manage the entire execution lifecycle

❌ **Don't use Mode A if:**
- You have a large existing codebase with custom orchestration
- You need framework-specific features that CEMAF doesn't support
- You want minimal changes to existing code

### Architecture

```
User
  ↓
DAGExecutor (CEMAF) ← Controls execution flow
  ↓
NodeExecutor ← Your implementation
  ↓
LangGraph/AutoGen/CrewAI ← Used as "engine"
  ↓
RunLogger (CEMAF) ← Automatic recording
  ↓
Replayer (CEMAF) ← Can replay later
```

### Basic Example

```python
from cemaf.orchestration import DAG, Node, Edge, DAGExecutor
from cemaf.observability import InMemoryRunLogger
from cemaf.context import Context

# 1. Define your DAG
dag = DAG(name="research_pipeline")
dag = dag.add_node(Node.tool(id="search", name="Search", tool_id="web_search"))
dag = dag.add_node(Node.tool(id="analyze", name="Analyze", tool_id="analyzer"))
dag = dag.add_edge(Edge(source="search", target="analyze"))

# 2. Create executor with logging
logger = InMemoryRunLogger()
executor = DAGExecutor(
    node_executor=my_node_executor,  # Your implementation
    run_logger=logger,  # Automatic recording
)

# 3. Execute
result = await executor.run(
    dag=dag,
    context=Context(data={"query": "AI agents"}),
)

# 4. Replay later for debugging
from cemaf.replay import Replayer
replayer = Replayer(logger.get_record(str(result.run_id)))
replay_result = await replayer.replay()
```

### Integrating LangGraph as Node Executor

```python
from cemaf.orchestration.executor import NodeExecutor, NodeResult
from cemaf.context import Context

class LangGraphNodeExecutor:
    """Adapter to use LangGraph as a node executor."""

    def __init__(self, langgraph_app):
        self.app = langgraph_app

    async def execute_node(
        self,
        node: Node,
        context: Context,
    ) -> NodeResult:
        try:
            # Convert CEMAF context to LangGraph state
            state = context.to_dict()

            # Run LangGraph
            result = await self.app.ainvoke(state)

            return NodeResult(
                node_id=node.id,
                success=True,
                output=result,
            )
        except Exception as e:
            return NodeResult(
                node_id=node.id,
                success=False,
                error=str(e),
            )

# Use with CEMAF
from langgraph.graph import StateGraph

# Your LangGraph app
graph = StateGraph(...)
langgraph_app = graph.compile()

# Wrap it for CEMAF
executor = DAGExecutor(
    node_executor=LangGraphNodeExecutor(langgraph_app),
    run_logger=InMemoryRunLogger(),
)
```

### Integrating AutoGen

```python
class AutoGenNodeExecutor:
    """Adapter to use AutoGen as a node executor."""

    def __init__(self, agents: dict[str, Agent]):
        self.agents = agents

    async def execute_node(
        self,
        node: Node,
        context: Context,
    ) -> NodeResult:
        agent_id = node.config.get("agent_id")
        agent = self.agents.get(agent_id)

        if not agent:
            return NodeResult(
                node_id=node.id,
                success=False,
                error=f"Agent '{agent_id}' not found",
            )

        try:
            result = await agent.run(context.to_dict())
            return NodeResult(
                node_id=node.id,
                success=True,
                output=result,
            )
        except Exception as e:
            return NodeResult(
                node_id=node.id,
                success=False,
                error=str(e),
            )
```

### Advanced Features in Mode A

#### Parallel Execution

```python
dag = DAG(name="parallel_research")
dag = dag.add_node(Node.tool("search_google"))
dag = dag.add_node(Node.tool("search_arxiv"))
dag = dag.add_node(Node.parallel("analyze", children=["search_google", "search_arxiv"]))
dag = dag.add_node(Node.tool("synthesize"))

# Both searches run in parallel, then analyze runs
```

#### Conditional Routing

```python
dag = dag.add_node(Node.router(
    id="route_by_quality",
    condition=Condition(
        field="search_results.quality_score",
        operator=ConditionOperator.GREATER_THAN,
        value=0.8,
    ),
))

# Routes to different nodes based on context
```

#### Checkpointing

```python
from cemaf.orchestration.checkpointer import InMemoryCheckpointer

executor = DAGExecutor(
    node_executor=my_executor,
    checkpointer=InMemoryCheckpointer(),  # Saves state for resume
)
```

---

## Mode B: CEMAF as Library

**External frameworks orchestrate.** CEMAF provides context management, patching, and recording infrastructure.

### When to Use Mode B

✅ **Use Mode B if:**
- You have an existing agent system (LangGraph, AutoGen, CrewAI, etc.)
- You want to add CEMAF features incrementally
- You need to keep your existing orchestration logic
- You want minimal changes to existing code

❌ **Don't use Mode B if:**
- You're starting from scratch (use Mode A instead)
- You need automatic replay (requires more setup in Mode B)
- You want CEMAF's advanced DAG features

### Architecture

```
LangGraph/AutoGen/CrewAI (orchestrates)
  ↓
Your Nodes
  ↓
CEMAF Context/Patches (infrastructure)
  ↓
RunLogger (manual recording)
```

### Basic Example with LangGraph

```python
from langgraph.graph import StateGraph
from cemaf.context import Context, ContextPatch, PatchSource
from cemaf.observability import InMemoryRunLogger

# Shared logger across nodes
run_logger = InMemoryRunLogger()

@langgraph_node
def search_node(state: dict) -> dict:
    # 1. Convert to CEMAF context
    ctx = Context.from_dict(state)

    # 2. Execute your logic
    results = web_search(ctx.get("query"))

    # 3. Create patch with provenance
    patch = ContextPatch.from_tool(
        tool_id="web_search",
        path="search_results",
        value=results,
        correlation_id=state.get("run_id", ""),
    )

    # 4. Apply patch and record
    ctx = ctx.apply(patch)
    run_logger.record_patch(patch)

    # 5. Convert back to dict
    return ctx.to_dict()

@langgraph_node
def analyze_node(state: dict) -> dict:
    ctx = Context.from_dict(state)

    # Use context
    results = ctx.get("search_results")
    analysis = analyze(results)

    # Track with patch
    patch = ContextPatch.from_tool(
        tool_id="analyzer",
        path="analysis",
        value=analysis,
    )
    ctx = ctx.apply(patch)
    run_logger.record_patch(patch)

    return ctx.to_dict()

# Build LangGraph (your existing code)
graph = StateGraph()
graph.add_node("search", search_node)
graph.add_node("analyze", analyze_node)
graph.add_edge("search", "analyze")
app = graph.compile()

# Run with CEMAF tracking
run_id = "run-123"
run_logger.start_run(
    run_id=run_id,
    initial_context=Context(data={"query": "AI agents"}),
)

result = await app.ainvoke({"query": "AI agents", "run_id": run_id})

record = run_logger.end_run(
    final_context=Context.from_dict(result),
)
```

### Using Token Budgeting

```python
from cemaf.context import TokenBudget, create_context_compiler_from_config

# Recommended: Use factory (auto-configures from .env)
compiler = create_context_compiler_from_config()

# Or manual setup
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
estimator = SimpleTokenEstimator()
compiler = PriorityContextCompiler(token_estimator=estimator)

# Define budget
budget = TokenBudget(
    max_tokens=4000,
    reserved_for_output=500,
)

# Compile context within budget
compiled = await compiler.compile(
    artifacts=(("brief", brief_content),),
    memories=(("history", conversation_history),),
    budget=budget,
    priorities={"brief": 10, "history": 5},  # brief prioritized
)

# Use compiled context with any LLM
messages = compiled.to_messages()
result = await llm_client.complete(messages)
```

### Using Scoped Memory

```python
from cemaf.memory import create_memory_store_from_config, MemoryItem
from cemaf.core.enums import MemoryScope
from datetime import timedelta

# Recommended: Use factory (auto-configures from .env)
store = create_memory_store_from_config()

# Or manual setup
from cemaf.memory import InMemoryStore
store = InMemoryStore()

# Set with TTL (expires in 1 hour)
await store.set(MemoryItem(
    scope=MemoryScope.SESSION,
    key="temp_data",
    value={"data": "temporary"},
    ttl=timedelta(hours=1),
))

# Get (returns None after TTL expires)
item = await store.get(MemoryScope.SESSION, "temp_data")

# Different scopes for different lifetimes
await store.set(MemoryItem(
    scope=MemoryScope.TENANT,
    key="tenant_style_guide",
    value={"tone": "professional"},
    # No TTL = permanent
))
```

### Using Execution Context (Cancellation/Timeout)

```python
from cemaf.core.execution import ExecutionContext, CancellationToken

# Create execution context
token = CancellationToken()
ctx = ExecutionContext(
    cancellation_token=token,
    timeout_ms=30000,  # 30 second timeout
)

# Wrap any coroutine
result = await with_execution_context(
    my_long_running_task(),
    ctx,
)

# Cancel from elsewhere (e.g., user clicks cancel)
token.cancel(reason="User requested cancellation")
```

---

## Migration Path: Mode B → Mode A

If you start with Mode B and want to migrate to Mode A:

### Step 1: Start with Context (Mode B)
```python
# Replace dict state with Context
ctx = Context.from_dict(existing_state)
```

### Step 2: Add Patching (Mode B)
```python
# Track changes with ContextPatch
patch = ContextPatch.from_tool("my_tool", "result", result_value)
ctx = ctx.apply(patch)
```

### Step 3: Enable Recording (Mode B)
```python
# Add RunLogger
run_logger.record_patch(patch)
```

### Step 4: Add Replay (Mode B)
```python
# Use Replayer for testing
replayer = Replayer(record)
replay_result = await replayer.replay()
```

### Step 5: Full Integration (Mode A)
```python
# Consider DAGExecutor for new workflows
executor = DAGExecutor(
    node_executor=YourFrameworkExecutor(),
    run_logger=InMemoryRunLogger(),
)
```

---

## Common Patterns

### Pattern 1: Minimal Integration (Just Provenance)

```python
from cemaf.context import Context, ContextPatch

# In your existing code
ctx = Context.from_dict(existing_state)
patch = ContextPatch.from_tool("my_tool", "result", result_value)
ctx = ctx.apply(patch)
new_state = ctx.to_dict()
```

### Pattern 2: Full Recording

```python
from cemaf.observability import InMemoryRunLogger

logger = InMemoryRunLogger()
logger.start_run("run-123", initial_context=Context())

# In your nodes
patch = ContextPatch.from_tool("tool", "path", value)
logger.record_patch(patch)

# At end
record = logger.end_run(final_context=ctx)
```

### Pattern 3: Token Budgeting Only

```python
from cemaf.context import TokenBudget, ContextCompiler

budget = TokenBudget.for_model("gpt-4")
compiler = PriorityContextCompiler(token_estimator=estimator)

compiled = await compiler.compile(
    artifacts=(("brief", content),),
    budget=budget,
)
messages = compiled.to_messages()
```

### Pattern 4: Memory with Scoping

```python
from cemaf import MemoryScope
from cemaf.memory import InMemoryStore

store = InMemoryStore()

# Session-scoped (temporary)
await store.set(MemoryItem(
    scope=MemoryScope.SESSION,
    key="temp",
    value={...},
    ttl=timedelta(hours=1),
))

# Tenant-scoped (permanent)
await store.set(MemoryItem(
    scope=MemoryScope.TENANT,
    key="guidelines",
    value={...},
))
```

---

## Choosing the Right Mode

### Use Mode A When:
- 🆕 Starting a new project
- 🎯 Need full CEMAF features (replay, provenance, advanced DAGs)
- 🔄 Want automatic recording and replay
- 🚀 Need parallel execution, routing, checkpointing

### Use Mode B When:
- 📦 Have existing codebase
- 🔧 Want gradual adoption
- 🎨 Need framework-specific features
- 💡 Only need specific CEMAF features (context, memory, etc.)

---

## Next Steps

1. **Quick Start**: See [docs/quickstart.md](docs/quickstart.md)
2. **Architecture**: See [docs/architecture.md](docs/architecture.md)
3. **Integration Guide**: See [docs/integration.md](docs/integration.md)
4. **Context Management**: See [docs/context.md](docs/context.md)
5. **Full Documentation**: See [docs/README.md](docs/README.md)

---

## Examples

- **Mode A Examples**: See `examples/hello_world_poc/` and `examples/simple_dag/`
- **Mode B Examples**: See `meridiansight/` and `soluna_arcana/` (real-world integrations)

---

## Questions?

- **Which mode should I use?** → Start with Mode B if you have existing code, Mode A if starting fresh
- **Can I switch modes?** → Yes! Start with Mode B, migrate to Mode A gradually
- **Do I need both modes?** → No, pick one based on your needs
- **Can I use CEMAF features standalone?** → Yes! Context, Memory, TokenBudgeting work independently
