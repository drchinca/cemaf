# LLM Module: Language Model Client Abstraction

## Overview

The `llm` module provides a **protocol-based abstraction layer** for language model clients, enabling seamless integration with multiple LLM providers (OpenAI, Anthropic, local models) while maintaining consistent interfaces across CEMAF.

**Key Purpose**: Decouple LLM provider from CEMAF framework
**Main Components**: `LLMClient`, `Message`, `CompletionResult`, `ToolCall`
**When to Use**: Every time you need LLM interaction, use the abstraction not providers directly

---

## Core Concepts

### Protocol-First Design

```python
from cemaf.llm import LLMClient, Message, Role, CompletionResult

# Protocol ensures any LLM backend is compatible
class LLMClient(Protocol):
    async def complete(
        self,
        messages: list[Message],
        **kwargs,
    ) -> CompletionResult:
        """Execute completion request."""
        ...
```

**Why**: Enables testing with MockLLMClient, swapping providers, custom implementations

### Message Architecture

```python
from enum import Enum

class Role(Enum):
    SYSTEM = "system"      # System instructions
    USER = "user"          # User query
    ASSISTANT = "assistant"  # LLM response
    TOOL = "tool"          # Tool result

@dataclass(frozen=True)
class Message:
    role: Role
    content: str
    tool_calls: list["ToolCall"] | None = None
    tool_call_id: str | None = None
```

**Flow**: System instruction → User query → Assistant response → (Optional) Tool call → Tool result

### Tool Calling Schema

```python
@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict  # JSON Schema
    required: list[str]

@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str  # Tool name
    arguments: dict  # Parsed JSON
```

**Purpose**: Enable LLM to call functions (CEMAF tools)

---

## Usage Examples

### Basic Completion

```python
from cemaf.llm import LLMClient, Message, Role
from cemaf.llm.anthropic import AnthropicLLMClient

# Initialize client
llm = AnthropicLLMClient(api_key="sk-...")

# Build conversation
messages = [
    Message(role=Role.SYSTEM, content="You are a helpful assistant."),
    Message(role=Role.USER, content="What is 2+2?"),
]

# Execute
result = await llm.complete(messages)
print(result.text)  # "2 + 2 = 4"
print(result.stop_reason)  # "end_turn"
```

### Tool Calling (Function Calling)

```python
# Define available tools
tools = [
    ToolDefinition(
        name="search",
        description="Search the web",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            }
        },
        required=["query"],
    )
]

# Send with tools
messages = [
    Message(role=Role.USER, content="Find information about Claude."),
]

result = await llm.complete(messages, tools=tools)

# Check for tool calls
if result.tool_calls:
    for tool_call in result.tool_calls:
        print(f"Tool: {tool_call.name}")
        print(f"Args: {tool_call.arguments}")

        # Execute tool
        if tool_call.name == "search":
            search_result = search(tool_call.arguments["query"])

            # Provide result back to LLM
            messages.append(result.message)
            messages.append(
                Message(
                    role=Role.TOOL,
                    content=search_result,
                    tool_call_id=tool_call.id,
                )
            )

            # Continue conversation
            final_result = await llm.complete(messages)
            print(final_result.text)
```

### Streaming Completions

```python
from cemaf.streaming import StreamHandler, StreamEvent

class PrintHandler(StreamHandler):
    async def on_stream(self, event: StreamEvent):
        if event.type == "text_delta":
            print(event.data, end="", flush=True)

# Stream with custom handler
handler = PrintHandler()
result = await llm.complete(messages, stream_handler=handler)
```

### Anti-Pattern: Direct Provider Usage

```python
# ❌ WRONG - Creates tight coupling
from openai import OpenAI
client = OpenAI()
response = client.chat.completions.create(...)
# Now you're locked into OpenAI API

# ✅ RIGHT - Uses abstraction
from cemaf.llm import LLMClient
llm: LLMClient = get_llm_client()  # Could be any provider
result = await llm.complete(messages)
# Easily swap providers or test with mock
```

---

## Integration

### With Tools (Tool Calling)

```python
from cemaf.tools import Tool
from cemaf.llm import ToolDefinition

# Convert CEMAF tool to LLM schema
tool: Tool = SearchTool()
schema = tool.get_schema()  # Returns ToolDefinition

# Use in LLM call
result = await llm.complete(messages, tools=[schema])

# Execute tool call
if result.tool_calls:
    for tool_call in result.tool_calls:
        output = await tool.execute(**tool_call.arguments)
```

### With Context (Token Budget)

```python
from cemaf.context import TokenBudget
from cemaf.llm import SimpleTokenEstimator

# Respect token budget in LLM calls
budget = TokenBudget.from_total(4000)
estimator = SimpleTokenEstimator()

# Check message token count
tokens_used = estimator.estimate("\n".join(m.content for m in messages))
if tokens_used > budget.remaining:
    # Trim messages or reject request
    raise ValueError("Token budget exceeded")

# Execute within budget
result = await llm.complete(messages, max_tokens=budget.remaining - 500)
```

### With Caching

```python
from cemaf.cache import TTLCache
from functools import wraps

# Cache LLM responses
cache = TTLCache(ttl_seconds=3600)

@wraps(llm.complete)
async def cached_complete(messages, **kwargs):
    # Create cache key from messages
    key = hash(tuple((m.role, m.content) for m in messages))

    # Check cache
    if key in cache:
        return cache[key]

    # Execute and cache
    result = await llm.complete(messages, **kwargs)
    cache[key] = result
    return result
```

### With Observability

```python
from cemaf.observability import Logger, Tracer

# Log LLM calls
logger = Logger()
tracer = Tracer()

async def traced_complete(messages, **kwargs):
    with tracer.trace("llm_complete"):
        logger.info("Starting LLM call", extra={
            "message_count": len(messages),
            "kwargs": kwargs,
        })

        result = await llm.complete(messages, **kwargs)

        logger.info("LLM call completed", extra={
            "stop_reason": result.stop_reason,
            "tokens_used": result.tokens_used,
        })

        return result
```

---

## API Reference

### LLMClient Protocol

```python
class LLMClient(Protocol):
    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stop_sequences: list[str] | None = None,
        stream_handler: StreamHandler | None = None,
        **kwargs,
    ) -> CompletionResult:
        """Execute LLM completion.

        Args:
            messages: Conversation messages
            tools: Available tools for function calling
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum response tokens
            stop_sequences: Sequences that stop generation
            stream_handler: Handler for streaming chunks

        Returns:
            CompletionResult with response and metadata
        """
```

### CompletionResult

```python
@dataclass(frozen=True)
class CompletionResult:
    text: str                              # Response text
    stop_reason: str                       # Why generation stopped
    tokens_used: int                       # Tokens in response
    tool_calls: list[ToolCall] | None = None  # Function calls
    message: Message = field(init=False)   # Full message object

    @property
    def message(self) -> Message:
        """Return as Message object."""
        return Message(
            role=Role.ASSISTANT,
            content=self.text,
            tool_calls=self.tool_calls,
        )
```

### Message

```python
@dataclass(frozen=True)
class Message:
    role: Role
    content: str
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
```

---

## Best Practices

### 1. Always Use Protocol

```python
# ✅ Type hint with protocol
def my_function(llm: LLMClient) -> str:
    # Can use any LLM implementation
    return await llm.complete(messages)

# ❌ Avoid specific implementations
def my_function(llm: AnthropicLLMClient) -> str:
    # Only works with Anthropic
    return await llm.complete(messages)
```

### 2. Manage Token Budget

```python
# ✅ Check budget before calling
if estimator.estimate(str(messages)) > budget.remaining:
    raise ValueError("Insufficient tokens")

result = await llm.complete(
    messages,
    max_tokens=min(500, budget.remaining - 100),
)
```

### 3. Handle Tool Calling Properly

```python
# ✅ Validate tool calls
if result.tool_calls:
    for tool_call in result.tool_calls:
        if tool_call.name not in available_tools:
            logger.warning(f"Unknown tool: {tool_call.name}")
            continue

        tool = available_tools[tool_call.name]
        try:
            output = await tool.execute(**tool_call.arguments)
        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            output = f"Error: {e}"

        # Always return result to LLM
        messages.append(result.message)
        messages.append(
            Message(
                role=Role.TOOL,
                content=str(output),
                tool_call_id=tool_call.id,
            )
        )
```

### 4. Implement Timeout

```python
import asyncio

# ✅ Set timeout for long-running calls
try:
    result = await asyncio.wait_for(
        llm.complete(messages),
        timeout=30.0,
    )
except asyncio.TimeoutError:
    logger.error("LLM call timed out")
    raise
```

### 5. Performance Tuning

```python
# ✅ Batch similar requests
messages_batch = [
    [Message(role=Role.USER, content=q) for q in queries]
    for queries in query_batches
]

# Execute in parallel
tasks = [llm.complete(msgs) for msgs in messages_batch]
results = await asyncio.gather(*tasks)

# ❌ Avoid sequential calls
for query in queries:
    result = await llm.complete([Message(role=Role.USER, content=query)])
```

### When NOT to Use LLM

```python
# ❌ Don't use LLM for
- Deterministic logic (use code)
- Real-time requirements (latency 0.5-2s)
- Private data (model trained on it)
- Financial calculations (imprecise)
- Time-critical operations

# ✅ Use LLM for
- Natural language understanding
- Text generation and synthesis
- Classification and reasoning
- Translation and summarization
- Multi-step problem solving
```

---

## Common Integration Patterns

### Pattern 1: Agent with Tool Calling

```python
async def agent_step(agent_state: dict, llm: LLMClient, tools: dict[str, Tool]) -> dict:
    """Execute one step of agent loop."""
    messages = agent_state["messages"]

    # Call LLM with available tools
    result = await llm.complete(
        messages,
        tools=[t.get_schema() for t in tools.values()],
    )

    # Add response to history
    messages.append(result.message)
    agent_state["messages"] = messages

    # Execute tool calls
    if result.tool_calls:
        for tool_call in result.tool_calls:
            tool = tools[tool_call.name]
            output = await tool.execute(**tool_call.arguments)

            # Add tool result
            messages.append(
                Message(
                    role=Role.TOOL,
                    content=str(output),
                    tool_call_id=tool_call.id,
                )
            )
    else:
        # Agent decided to stop
        agent_state["status"] = "complete"

    return agent_state
```

### Pattern 2: RLM with LLM

```python
from cemaf.rlm import RLMQueryTool

# RLM uses LLMClient internally
rlm_tool = RLMQueryTool(
    engine=DivideAndConquerQueryEngine(
        llm_client=llm,  # Uses your LLMClient
        compiler=compiler,
        max_depth=3,
    ),
    chunking=FixedSizeChunkingStrategy(estimator, chunk_size=500),
)

# Query large document
result = await rlm_tool.execute(
    instruction="Summarize the key themes",
    content=large_document,
)
```

### Pattern 3: Streaming UI Updates

```python
from cemaf.streaming import StreamHandler, StreamEvent

class UIUpdateHandler(StreamHandler):
    def __init__(self, update_callback):
        self.update_callback = update_callback
        self.buffer = ""

    async def on_stream(self, event: StreamEvent):
        if event.type == "text_delta":
            self.buffer += event.data
            # Update UI in real-time
            await self.update_callback(self.buffer)

# Use in web endpoint
handler = UIUpdateHandler(websocket.send)
result = await llm.complete(messages, stream_handler=handler)
```

---

## Configuration

### Environment Setup

```bash
# Anthropic
export ANTHROPIC_API_KEY="sk-..."

# OpenAI
export OPENAI_API_KEY="sk-..."

# Local model
export LLM_PROVIDER="local"
export LLM_MODEL_PATH="/path/to/model"
```

### Initialization Options

```python
from cemaf.config import SettingsProvider

settings = SettingsProvider.from_env()

# Automatic provider selection based on environment
llm = get_llm_client(
    provider=settings.get("llm_provider", "anthropic"),
    model=settings.get("llm_model", "claude-3-sonnet-20240229"),
)
```

---

## Troubleshooting

### Issue: Tool Call Argument Mismatch

```python
# Problem: Tool expects 'query' but LLM sends 'search_query'
# Solution: Validate and map

expected_args = tool.get_schema().parameters["required"]
actual_args = tool_call.arguments

missing = set(expected_args) - set(actual_args.keys())
if missing:
    logger.warning(f"Missing arguments: {missing}")
    # Either reject or use defaults
```

### Issue: Token Limit Exceeded

```python
# Problem: Accumulated messages exceed limit
# Solution: Sliding window

max_tokens = 4000
while estimator.estimate(str(messages)) > max_tokens:
    # Remove oldest non-system message
    messages = [messages[0]] + messages[2:]  # Keep system, remove next oldest
```

### Issue: LLM Refuses to Call Tools

```python
# Problem: LLM doesn't use provided tools
# Solution: Add explicit prompt

system_message = Message(
    role=Role.SYSTEM,
    content="Use the search tool to find information."
    "Format tool calls exactly as specified."
)
messages = [system_message] + messages
result = await llm.complete(messages, tools=tools)
```

---

**Related Documentation**:
- [Context Module](./context.md) - Token budgeting
- [Tools Module](./tools.md) - Tool definition
- [RLM Module](./rlm.md) - Recursive querying
- [Streaming Module](./streaming.md) - Real-time output
