# Context Engineering Agents

The Context Engineering Agents are a set of four specialized agents designed to implement semantic blueprint-based content generation workflows. They enable autonomous, context-aware execution pipelines with cost tracking and resilient context chaining.

## Overview

Context Engineering Agents implement a **semantic blueprint workflow** where:
1. **Librarian** retrieves style/structure blueprints from a vector store
2. **Researcher** synthesizes factual information with high-fidelity retrieval
3. **Summarizer** reduces context density for token management
4. **Writer** generates final content using blueprints and facts

All agents follow CEMAF patterns: protocol-based design, explicit dependency injection, generic typing, and immutable state.

## The Four Agents

### 1. Librarian Agent

Retrieves semantic blueprints (style instructions) from a vector store.

**Purpose**: Fetch context-specific instructions for content generation

**Goal Type**:
```python
class LibrarianGoal(BaseModel):
    intent_query: str  # Descriptive phrase of desired style
```

**Result Type**:
```python
class LibrarianResult(BaseModel):
    blueprint_json: str  # Blueprint structure as JSON string
```

**Configuration**:
- `vector_store`: VectorStore protocol (required)
- `namespace_context`: Namespace for blueprint storage (default: "blueprints")
- `top_k`: Number of results to retrieve (default: 1)

**Example**:
```python
from cemaf.agents.context_agents import LibrarianAgent, LibrarianGoal
from cemaf.agents.base import AgentContext

librarian = LibrarianAgent(
    vector_store=my_vector_store,
    namespace_context="blueprints",
    top_k=1,
)

goal = LibrarianGoal(intent_query="professional audit report style")
context = AgentContext(run_id="run_123", agent_id="test")
result = await librarian.run(goal, context)

# result.output.blueprint_json contains the retrieved blueprint
```

### 2. Researcher Agent

Retrieves facts with high-fidelity (k=15) and synthesizes them using an LLM.

**Purpose**: Gather comprehensive evidence and synthesize factual information

**Goal Type**:
```python
class ResearcherGoal(BaseModel):
    topic_query: str  # Subject matter to research
```

**Result Type**:
```python
class ResearcherResult(BaseModel):
    facts: str  # Synthesized factual report
```

**Configuration**:
- `vector_store`: VectorStore protocol (required)
- `llm_client`: LLMClient protocol (required)
- `namespace_knowledge`: Namespace for knowledge storage (default: "knowledge")
- `top_k`: Retrieval count for high-fidelity gathering (default: 15)

**Key Features**:
- High-fidelity retrieval ensures all relevant documents captured
- LLM synthesis aggregates evidence with source attribution
- Token telemetry included in metadata for cost tracking

**Example**:
```python
from cemaf.agents.context_agents import ResearcherAgent, ResearcherGoal

researcher = ResearcherAgent(
    vector_store=my_vector_store,
    llm_client=my_llm,
    namespace_knowledge="knowledge",
    top_k=15,
)

goal = ResearcherGoal(topic_query="AI safety and governance")
result = await researcher.run(goal, context)

# result.output.facts contains synthesized findings
# result.metadata contains token usage and cost
```

### 3. Summarizer Agent

Reduces context density by compressing long text while preserving key information.

**Purpose**: Manage token budgets and context window constraints

**Goal Type**:
```python
class SummarizerGoal(BaseModel):
    text_to_summarize: str
    summary_objective: str  # Clear goal for the summary
```

**Result Type**:
```python
class SummarizerResult(BaseModel):
    summary: str  # Compressed summary text
```

**Configuration**:
- `llm_client`: LLMClient protocol (required)

**Special Metadata**:
- `tokens_saved`: Calculated as (tokens_in - tokens_out)
- `compression_ratio`: Calculated as tokens_out / tokens_in

**Example**:
```python
from cemaf.agents.context_agents import SummarizerAgent, SummarizerGoal

summarizer = SummarizerAgent(llm_client=my_llm)

goal = SummarizerGoal(
    text_to_summarize=long_research_text,
    summary_objective="Extract key technical specifications",
)
result = await summarizer.run(goal, context)

# result.metadata["tokens_saved"] shows compression benefit
# result.metadata["compression_ratio"] shows efficiency
```

### 4. Writer Agent

Generates final content by applying a blueprint to source material.

**Purpose**: Deterministic content generation with style consistency

**Goal Type**:
```python
class WriterGoal(BaseModel):
    blueprint: str | dict  # Style instructions
    facts: str | dict | None  # Factual information
    previous_content: str | None  # Content for rewriting
```

**Result Type**:
```python
class WriterResult(BaseModel):
    report: str  # Generated content
```

**Configuration**:
- `llm_client`: LLMClient protocol (required)

**Input Flexibility**:
- Accepts JSON strings, dicts, or Blueprint objects
- Handles various input formats automatically
- Requires either `facts` or `previous_content`

**Example**:
```python
from cemaf.agents.context_agents import WriterAgent, WriterGoal

writer = WriterAgent(llm_client=my_llm)

goal = WriterGoal(
    blueprint=json.dumps({"style": "professional", "tone": "formal"}),
    facts="Research findings about AI safety...",
)
result = await writer.run(goal, context)

# result.output.report contains generated content
```

## Agent Registry

The `AgentRegistry` provides a centralized way to discover and create agents.

### Basic Usage

```python
from cemaf.agents.registry import AgentRegistry

registry = AgentRegistry()

# List available agents
agents = registry.list_agents()
# ['Librarian', 'Researcher', 'Summarizer', 'Writer']

# Get agent class
agent_class = registry.get_agent_class("Librarian")

# Get goal type for validation
goal_type = registry.get_goal_type("Researcher")

# Create agent with dependencies
librarian = registry.create_agent(
    "Librarian",
    vector_store=my_vector_store,
    namespace_context="blueprints",
)
```

### Global Toolkit

A global `AGENT_TOOLKIT` instance is available:

```python
from cemaf.agents.registry import AGENT_TOOLKIT

agent = AGENT_TOOLKIT.create_agent(
    "Summarizer",
    llm_client=my_llm,
)
```

### Capabilities Description

Get structured descriptions for LLM-based planning:

```python
capabilities = registry.get_capabilities_description()
# Returns markdown-formatted description of all agents
# with required inputs and outputs for planning
```

## Autonomous Planning

The `Planner` generates DAGs from high-level goals using an LLM.

### How It Works

1. LLM receives goal + agent capabilities
2. LLM generates JSON plan with steps and inputs
3. Plan converted to executable DAG
4. Executor runs DAG with context chaining

### Example

```python
from cemaf.orchestration.planner import Planner

planner = Planner(llm_client=my_llm, agent_registry=registry)

goal = "Generate an audit report on AI safety policies"
dag = await planner.plan(goal)

# DAG has nodes for each agent with:
# - input_mapping: Parameters with $$STEP_N_OUTPUT$$ placeholders
# - output_key: STEP_N_OUTPUT for context chaining
```

## Context Chaining

Agents pass outputs to downstream nodes using placeholder resolution.

### Placeholder Format

Use `$$STEP_N_OUTPUT$$` to reference previous step outputs:

```python
plan = {
    "plan": [
        {"step": 1, "agent": "Librarian", "input": {"intent_query": "style"}},
        {"step": 2, "agent": "Researcher", "input": {"topic_query": "AI safety"}},
        {
            "step": 3,
            "agent": "Writer",
            "input": {
                "blueprint": "$$STEP_1_OUTPUT$$",  # Librarian output
                "facts": "$$STEP_2_OUTPUT$$",  # Researcher output
            },
        },
    ]
}
```

### Dependency Resolution

The executor automatically resolves placeholders:

```python
from cemaf.orchestration.dependency_resolver import resolve_node_input

context = Context(data={"STEP_1_OUTPUT": "blueprint_json", "STEP_2_OUTPUT": "facts"})
resolved = resolve_node_input(
    {"blueprint": "$$STEP_1_OUTPUT$$", "facts": "$$STEP_2_OUTPUT$$"},
    context,
)
# resolved == {"blueprint": "blueprint_json", "facts": "facts"}
```

## Token Telemetry

Track token usage and estimated costs for each agent.

### Metadata Fields

```python
metadata = {
    "tokens_in": 100,          # Input tokens
    "tokens_out": 50,          # Output tokens
    "tokens_total": 150,       # Total tokens
    "tokens_saved": 75,        # For Summarizer only
    "compression_ratio": 0.25, # For Summarizer only
    "cost_estimate_usd": 0.01, # Estimated cost
}
```

### Per-Agent Usage

```python
from cemaf.observability.token_telemetry import extract_token_metadata

# Extract from LLM result
metadata = extract_token_metadata(
    llm_result=result,
    agent_name="Summarizer",
)

# Or estimate from text
metadata = extract_token_metadata(
    input_text=text,
    output_text=summary,
    model="gpt-4",
    agent_name="Summarizer",
)
```

### Aggregation

```python
from cemaf.observability.token_telemetry import merge_token_metadata

# Aggregate results from multiple agents
all_metadata = [metadata1, metadata2, metadata3]
total = merge_token_metadata(all_metadata)

# total["cost_estimate_usd"] is workflow total cost
```

## Complete Workflow Example

```python
import json
from cemaf.agents.registry import AGENT_TOOLKIT
from cemaf.orchestration.planner import Planner
from cemaf.orchestration.executor import DAGExecutor
from cemaf.context.context import Context

# Setup
vector_store = create_vector_store()
llm_client = create_llm_client()
executor = DAGExecutor()

# Create plan
planner = Planner(llm_client=llm_client, agent_registry=AGENT_TOOLKIT)
dag = await planner.plan("Generate risk assessment for AI deployment")

# Execute with context tracking
context = Context()
final_context = await executor.execute_dag(dag, context)

# Get workflow output from final context
output = final_context.get("STEP_3_OUTPUT")  # Writer output
print(f"Generated report:\n{output}")

# Track costs
total_tokens = final_context.get("_total_tokens", 0)
total_cost = final_context.get("_total_cost", 0)
print(f"Total tokens: {total_tokens}, Cost: ${total_cost}")
```

## Best Practices

### 1. Use Registry for Discovery
Always use `AgentRegistry` for creating agents - enables extensibility and consistent configuration.

### 2. Provide Rich Blueprints
Blueprints are style instructions that guide Writer output. Make them detailed:
```json
{
  "objective": "Security audit report",
  "style": "professional",
  "tone": "formal",
  "structure": ["executive_summary", "findings", "recommendations"],
  "evidence_threshold": "2+ sources",
  "citations_required": true
}
```

### 3. Configure Retrieval K Values
- `Librarian`: top_k=1 (exact match)
- `Researcher`: top_k=15 (comprehensive evidence)

### 4. Monitor Token Usage
Always collect token metadata for cost optimization:
```python
result = await agent.run(goal, context)
if "tokens_saved" in result.metadata:
    savings = result.metadata["tokens_saved"]
    ratio = result.metadata["compression_ratio"]
    print(f"Compressed to {ratio*100:.1f}%, saved {savings} tokens")
```

### 5. Handle Agent Failures Gracefully
All agents return `AgentResult` with success flag:
```python
result = await agent.run(goal, context)
if not result.success:
    logger.error(f"Agent failed: {result.error}")
    # Fallback to default behavior
```

## Architecture Notes

### Protocol-Based Design
All dependencies use protocols (VectorStore, LLMClient) not concrete classes:
```python
from cemaf.llm.protocols import LLMClient
from cemaf.retrieval.protocols import VectorStore

# Any implementation matching the protocol works
librarian = LibrarianAgent(vector_store=my_custom_store)
```

### Generic Typing
Agents are generically typed for type safety:
```python
class Agent[GoalT: BaseModel, ResultT](ABC):
    async def run(self, goal: GoalT, context: AgentContext) -> AgentResult[ResultT]:
        ...
```

### Immutable Results
AgentResult is immutable for replay and audit:
```python
result = AgentResult.ok(output, state, metadata=metadata)
# result fields cannot be modified after creation
```

### Async-First
All operations are async-compatible:
```python
# Concurrent execution
results = await asyncio.gather(
    librarian.run(goal1, ctx),
    researcher.run(goal2, ctx),
)
```

## Related Documentation

- [Orchestration](./orchestration.md) - DAG execution and planning
- [Observability](./observability.md) - Comprehensive monitoring
- [LLM Integration](./llm.md) - LLMClient protocol details
- [Vector Stores](./retrieval.md) - VectorStore protocol details
