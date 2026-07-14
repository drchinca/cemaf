# Standalone Module Usage

CEMAF modules are designed to work **independently**. You can use any module without pulling in the entire framework. This guide shows how to use each module standalone.

## Core Principle

**Every CEMAF module can be used independently. Dependencies are optional and protocol-based.**

## Standalone Usage Examples

### 1. Context Management Only

Use CEMAF's context system without any other modules:

```python
from cemaf.context import Context, ContextPatch, PatchSource

# Create context
ctx = Context(data={"user": "Alice", "count": 0})

# Create patch
patch = ContextPatch.set(
    path="count",
    value=1,
    source=PatchSource.USER,
    reason="User incremented counter",
)

# Apply patch (returns new context)
new_ctx = ctx.apply(patch)

# Original unchanged
assert ctx.data["count"] == 0
assert new_ctx.data["count"] == 1
```

**No dependencies**: Works without LLM, tools, agents, or any other modules.

### 2. Tools Only

Create and use tools independently:

```python
from cemaf.tools.protocols import Tool
from cemaf.core.types import ToolID
from cemaf.tools.base import ToolSchema, ToolResult
from cemaf.core.result import Result

class CalculatorTool:
    """Simple calculator tool - no CEMAF dependencies."""

    @property
    def id(self) -> ToolID:
        return ToolID("calculator")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="calculator",
            description="Perform arithmetic",
            parameters={
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                    "op": {"type": "string", "enum": ["+", "-", "*", "/"]},
                },
                "required": ["a", "b", "op"],
            },
            required=("a", "b", "op"),
        )

    async def execute(self, a: float, b: float, op: str) -> ToolResult:
        try:
            if op == "+":
                result = a + b
            elif op == "-":
                result = a - b
            elif op == "*":
                result = a * b
            elif op == "/":
                result = a / b
            else:
                return Result.fail(f"Unknown operator: {op}")

            return Result.ok(result)
        except Exception as e:
            return Result.fail(str(e))

# Use tool standalone
tool = CalculatorTool()
result = await tool.execute(a=5, b=3, op="+")
assert result.success
assert result.data == 8
```

**No dependencies**: Tool works independently of agents, skills, or orchestration.

### 3. Context Compiler Only

Use context compilation without orchestration:

```python
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
from cemaf.context.budget import TokenBudget

# Create compiler
estimator = SimpleTokenEstimator(chars_per_token=4.0)
compiler = PriorityContextCompiler(estimator)

# Compile context
artifacts = (
    ("doc1", "This is document 1"),
    ("doc2", "This is document 2"),
)
memories = (
    ("memory1", "Previous conversation about X"),
)
budget = TokenBudget(max_tokens=1000)

compiled = await compiler.compile(
    artifacts=artifacts,
    memories=memories,
    budget=budget,
)

# Use compiled context
for source in compiled.sources:
    print(f"{source.key}: {source.content[:50]}...")
```

**No dependencies**: Compiler works without LLM, agents, or orchestration.

### 4. RLM Only

Use RLM for recursive querying without full agent framework:

```python
from cemaf.rlm import create_rlm_tool
from cemaf.llm.mock import MockLLMClient

# Create RLM tool with mock LLM (for testing)
llm = MockLLMClient(responses=["Found information about X"])
rlm = create_rlm_tool(llm_client=llm)

# Use RLM standalone
result = await rlm.execute(
    instruction="Find all mentions of CEMAF",
    content=very_large_document,
)

if result.success:
    print(f"Answer: {result.data}")
    print(f"LLM Calls: {result.metadata['llm_calls_made']}")
```

**Minimal dependencies**: Only needs an LLM client (protocol-based).

### 5. Memory Store Only

Use memory storage independently:

```python
from cemaf.memory import InMemoryStore, MemoryItem
from cemaf.core.enums import MemoryScope

# Create memory store
memory = InMemoryStore()

# Store memories
await memory.set(MemoryItem(scope=MemoryScope.USER, key="user_pref", value="dark_theme"))
await memory.set(
    MemoryItem(
        scope=MemoryScope.SESSION,
        key="conversation_1",
        value="User asked about X",
    )
)

# Retrieve memories
pref = await memory.get(MemoryScope.USER, "user_pref")
session_memories = await memory.list_by_scope(MemoryScope.SESSION)

# Use in your own code
print(f"User preference: {pref.value if pref else None}")
for item in session_memories:
    print(f"{item.key}: {item.value}")
```

**No dependencies**: Memory store works independently.

### 6. Citation Tracking Only

Track citations without full framework:

```python
from cemaf.citation import CitationTracker
from cemaf.retrieval.protocols import Document, SearchResult

# Create tracker
tracker = CitationTracker()

# Create search result (from your own retrieval system)
doc = Document(
    id="doc_123",
    content="CEMAF is a framework",
    metadata={"title": "CEMAF Docs", "url": "https://example.com"},
)
result = SearchResult(document=doc, score=0.95, rank=1)

# Track citation
citation = tracker.track_search_result(result)

# Create cited fact
fact = tracker.create_cited_fact(
    fact="CEMAF provides context management",
    citations=[citation],
    confidence=0.95,
)

# Get citation report
report = tracker.get_citation_report()
print(f"Total citations: {report['total_citations']}")
```

**Minimal dependencies**: Only needs retrieval types (data classes).

### 7. Moderation Only

Use moderation independently:

```python
from cemaf.moderation import ModerationPipeline, PreFlightGate, PostFlightGate
from cemaf.moderation.rules import KeywordRule, PIIRule

# Create moderation pipeline
pre_gate = PreFlightGate(rules=[KeywordRule(blocked_words=("spam",))])
post_gate = PostFlightGate(rules=[PIIRule()])
pipeline = ModerationPipeline(pre_flight=pre_gate, post_flight=post_gate)

# Check content
result = await pipeline.check_input("This is clean content")
assert result.allowed

result = await pipeline.check_input("This contains spam")
assert not result.allowed
assert len(result.violations) > 0
```

**No dependencies**: Moderation works independently.

### 8. Blueprint Only

Use blueprints for prompt engineering:

```python
from cemaf.blueprint import Blueprint, SceneGoal, StyleGuide

# Create blueprint
blueprint = Blueprint(
    id="blog_post",
    name="Blog Post Generator",
    scene_goal=SceneGoal(
        objective="Generate engaging blog post",
        success_criteria=("informative", "engaging"),
    ),
    style_guide=StyleGuide(
        tone="professional",
        format="markdown",
    ),
)

# Convert to prompt
prompt = blueprint.to_prompt()

# Use with any LLM (not CEMAF-specific)
response = await my_llm.complete(prompt)
```

**No dependencies**: Blueprints are just data structures.

## Mixing CEMAF with Your Code

### Pattern: Use CEMAF Context in Your Framework

```python
# Your existing framework
class MyAgent:
    def __init__(self):
        # Use CEMAF context
        from cemaf.context import Context
        self._context = Context(data={})

    async def process(self, input_data):
        # Your logic
        result = self._process(input_data)

        # Update CEMAF context
        from cemaf.context import ContextPatch, PatchSource
        patch = ContextPatch.set(
            path="results.latest",
            value=result,
            source=PatchSource.AGENT,
        )
        self._context = self._context.apply(patch)

        return result
```

### Pattern: Use CEMAF Tools in Your System

```python
# Your system
class MySystem:
    def __init__(self):
        # Use CEMAF tools
        from cemaf.tools import ToolRegistry
        self._tools = ToolRegistry()
        self._tools.register(MyCEMAFTool())

    async def execute(self, tool_name, **kwargs):
        tool = self._tools.get(tool_name)
        return await tool.execute(**kwargs)
```

### Pattern: Use CEMAF Compiler in LangChain

```python
# LangChain chain
from langchain.chains import LLMChain
from cemaf.context.compiler import PriorityContextCompiler

# Use CEMAF compiler
compiler = PriorityContextCompiler(estimator)
compiled = await compiler.compile(artifacts, memories, budget)

# Pass to LangChain
chain = LLMChain(llm=llm, prompt=compiled.to_messages())
response = chain.run(compiled.content)
```

## Protocol-Based Integration

When modules do integrate, they use protocols:

```python
# RLM accepts any ContextCompiler (protocol)
from cemaf.rlm import DivideAndConquerQueryEngine
from cemaf.context.compiler import ContextCompiler

class MyCompiler:
    async def compile(self, ...):
        ...

# Your compiler works with RLM
compiler: ContextCompiler = MyCompiler()
engine = DivideAndConquerQueryEngine(llm, compiler, max_depth=3)
```

## Dependency Graph

Understanding dependencies helps you use modules standalone:

```
Core (no dependencies)
├── context/ (depends on core only)
├── tools/ (depends on core only)
├── memory/ (depends on core only)
├── blueprint/ (depends on core only)
│
Infrastructure (depends on core)
├── llm/ (depends on core)
├── cache/ (depends on core)
├── events/ (depends on core)
│
Higher Level (depends on infrastructure)
├── skills/ (depends on tools)
├── agents/ (depends on skills, tools)
├── orchestration/ (depends on agents, context, observability)
├── rlm/ (depends on context, llm)
```

**Key Point**: Lower-level modules have fewer dependencies and can be used standalone.

## Best Practices

1. **Import Only What You Need**: Don't import entire framework
2. **Use Protocols**: Accept protocols, not concrete classes
3. **Minimal Dependencies**: Each module should work with minimal setup
4. **Test Standalone**: Test modules independently
5. **Document Dependencies**: Clearly document what each module needs

## Summary

- **Every module works standalone** - use only what you need
- **Protocols enable integration** - when you do integrate, use protocols
- **Defaults provided** - but replaceable with your own implementations
- **Mix freely** - combine CEMAF modules with your own code
- **No forced dependencies** - modules don't require the full framework

## Related Documentation

- [Protocol Guide](protocol_guide.md) - Understanding protocols
- [Extension Patterns](extension_patterns.md) - How to extend
- [Integration Guide](integration.md) - External framework integration
