# Tools

Tools are atomic, stateless functions that perform a single operation.

## Tool Architecture

```mermaid
flowchart TB
    subgraph Tool Definition
        SCHEMA[ToolSchema<br/>name, description, parameters]
        TOOL[Tool<br/>id, schema, execute]
    end

    subgraph Execution
        INPUT[Input kwargs]
        EXEC[execute]
        RESULT[Result T]
    end

    subgraph Recording
        LOGGER[RunLogger]
        CALL[ToolCall]
    end

    SCHEMA --> TOOL
    INPUT --> EXEC
    TOOL --> EXEC
    EXEC --> RESULT

    EXEC -.->|record| LOGGER
    LOGGER --> CALL
```

## Tool Execution Flow

```mermaid
sequenceDiagram
    participant Caller
    participant Tool
    participant Logger as RunLogger

    Caller->>Tool: execute(**kwargs)

    alt With Recording
        Caller->>Tool: execute_with_recording(logger, **kwargs)
        Tool->>Tool: execute(**kwargs)
        Tool->>Logger: record_tool_call(ToolCall)
    end

    Tool-->>Caller: Result[T]

    alt Success
        Note over Caller: result.success = True<br/>result.data = output
    else Failure
        Note over Caller: result.success = False<br/>result.error = message
    end
```

## Defining a Tool

```python
from cemaf.tools.base import Tool, ToolSchema
from cemaf.core.result import Result

class SearchTool(Tool):
    @property
    def id(self) -> str:
        return "search"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="search",
            description="Search the web",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"}
                }
            },
            required=("query",)
        )

    async def execute(self, query: str) -> Result[dict]:
        # Implementation
        try:
            results = perform_search(query)
            return Result.ok({"results": results})
        except Exception as e:
            return Result.fail(str(e))
```

## Tool Decorator

Quick way to create tools from functions:

```python
from cemaf.tools.base import tool

@tool(
    id="calculate",
    name="calculate",
    description="Perform arithmetic",
    parameters={"type": "object", "properties": {"expression": {"type": "string"}}}
)
async def calculate(expression: str) -> dict:
    result = eval(expression)
    return {"result": result}
```

## Tool Schema

Define parameters using JSON Schema:

```python
schema = ToolSchema(
    name="my_tool",
    description="Tool description",
    parameters={
        "type": "object",
        "properties": {
            "param1": {"type": "string"},
            "param2": {"type": "number"}
        }
    },
    required=("param1",)
)

# Convert to LLM formats
openai_format = schema.to_openai_format()
anthropic_format = schema.to_anthropic_format()
```

## Tool Execution

Tools always return `Result[T]` and never raise exceptions:

```python
result = await tool.execute(query="test")

if result.success:
    data = result.data
else:
    error = result.error
```

## Real-World Example: RLM Query Tool

RLM (Recursive Language Models) is a CEMAF tool for querying large context:

```python
from cemaf.rlm import create_rlm_tool
from cemaf.llm.anthropic import AnthropicLLMClient

# Create LLM client
llm = AnthropicLLMClient(api_key="...")

# Create RLM tool
rlm_tool = create_rlm_tool(
    llm_client=llm,
    chunk_size=500,
    max_depth=3,
    max_tokens=4000,
)

# Tool implements standard protocol
assert rlm_tool.id == "rlm_query"
assert rlm_tool.schema.name == "rlm_query"

# Execute query on large content
result = await rlm_tool.execute(
    instruction="Find all mentions of CEMAF",
    content=large_document,  # 100K+ tokens
)

# Always returns Result
if result.success:
    print(f"Answer: {result.data}")
    print(f"Metadata: {result.metadata}")
    # → depth_reached, chunks_examined, llm_calls_made, total_tokens_used
else:
    print(f"Error: {result.error}")

# Use in ToolRegistry for LLM function calling
from cemaf.tools.registry import ToolRegistry

registry = ToolRegistry(namespace="analysis")
registry.register_instance(rlm_tool)

# Export for Claude/GPT
anthropic_schemas = registry.to_anthropic_schemas()
# → [{"name": "analysis.rlm_query", "description": "...", "input_schema": {...}}]
```

**See Also**: [RLM Documentation](./rlm.md)
