# Model Context Protocol (MCP) Integration

The MCP module provides integration with the Model Context Protocol (JSON-RPC 2.0), enabling CEMAF to expose its tools, resources, and prompts as MCP-compatible services.

## Overview

MCP is a protocol for connecting AI assistants to external data sources and tools. CEMAF's MCP adapter bridges CEMAF components to MCP, allowing:

- **Tools**: CEMAF tools exposed as MCP tools
- **Resources**: CEMAF memory stores exposed as MCP resources
- **Prompts**: CEMAF blueprints exposed as MCP prompts

## Architecture

```
┌─────────────┐
│ MCP Client  │
└──────┬──────┘
       │ JSON-RPC 2.0
       │
┌──────▼──────────┐
│  MCPAdapter     │
│  (JSON-RPC)     │
└──────┬──────────┘
       │
   ┌───┴────┬──────────┬──────────┐
   │        │          │          │
┌──▼──┐ ┌──▼──┐   ┌───▼───┐  ┌───▼───┐
│Tool │ │Res  │   │Prompt │  │Events │
│Bridge│ │Bridge│   │Bridge │  │       │
└──┬──┘ └──┬──┘   └───┬───┘  └───┬───┘
   │        │          │          │
┌──▼──┐ ┌──▼──┐   ┌───▼───┐  ┌───▼───┐
│Tool │ │Mem  │   │Blue-  │  │Event  │
│     │ │Store│   │print  │  │Bus    │
└─────┘ └─────┘   └───────┘  └───────┘
```

## Core Components

### MCPAdapter

The `MCPAdapter` is the main entry point for MCP integration:

```python
from cemaf.mcp import MCPAdapter
from cemaf.tools import ToolRegistry
from cemaf.memory import MemoryStore
from cemaf.blueprint import Blueprint

adapter = MCPAdapter(
    tools=ToolRegistry([my_tool1, my_tool2]),
    memory_store=my_memory_store,
    blueprints=[blueprint1, blueprint2],
    event_bus=my_event_bus,
    run_logger=my_run_logger,
)
```

### Transports

MCP supports multiple transport mechanisms:

#### StdioTransport

Standard input/output transport (for CLI tools):

```python
from cemaf.mcp import StdioTransport

transport = StdioTransport()
await adapter.serve(transport)
```

#### WebSocketTransport

WebSocket transport for web applications:

```python
from cemaf.mcp import WebSocketTransport

transport = WebSocketTransport(url="ws://localhost:8080/mcp")
await adapter.serve(transport)
```

#### SSETransport

Server-Sent Events transport:

```python
from cemaf.mcp import SSETransport

transport = SSETransport(endpoint="/mcp/events")
await adapter.serve(transport)
```

## Bridges

Bridges convert CEMAF components to MCP format:

### ToolBridge

Converts CEMAF tools to MCP tool definitions:

```python
from cemaf.mcp import ToolBridge
from cemaf.tools import Tool

# Convert tool to MCP format
mcp_tool = ToolBridge.to_mcp(my_tool)

# Execute tool via MCP
result = await ToolBridge.call(
    tool=my_tool,
    arguments={"query": "search term"},
    run_logger=run_logger,
    correlation_id="req_123",
)
```

### ResourceBridge

Exposes memory stores as MCP resources:

```python
from cemaf.mcp import ResourceBridge
from cemaf.memory import MemoryStore

bridge = ResourceBridge(memory_store=my_memory_store)

# List available resources
resources = await bridge.list_resources()

# Get resource contents
contents = await bridge.get_resource("memory://conversation_123")
```

### PromptBridge

Converts blueprints to MCP prompts:

```python
from cemaf.mcp import PromptBridge
from cemaf.blueprint import Blueprint

bridge = PromptBridge(blueprints=[blueprint1, blueprint2])

# List available prompts
prompts = await bridge.list_prompts()

# Get prompt template
prompt = await bridge.get_prompt("blueprint://content_generation")
```

## MCP Protocol Types

### MCPRequest / MCPResponse

JSON-RPC 2.0 request/response format:

```python
from cemaf.mcp import MCPRequest, MCPResponse

request = MCPRequest(
    jsonrpc="2.0",
    method="tools/call",
    params={"name": "web_search", "arguments": {"query": "AI"}},
    id=1,
)

response = await adapter.handle_request(request)
```

### MCPError

Error handling with standard error codes:

```python
from cemaf.mcp import MCPError, MCPErrorCode

error = MCPError(
    code=MCPErrorCode.INVALID_PARAMS,
    message="Missing required parameter: query",
)
```

## Integration Examples

### Example 1: Expose Tools as MCP

```python
from cemaf.mcp import MCPAdapter, StdioTransport
from cemaf.tools import ToolRegistry

# Create adapter with tools
adapter = MCPAdapter(
    tools=ToolRegistry([web_search_tool, calculator_tool]),
)

# Serve via stdio
transport = StdioTransport()
await adapter.serve(transport)
```

### Example 2: Expose Memory as Resources

```python
from cemaf.mcp import MCPAdapter
from cemaf.memory import InMemoryMemoryStore

memory_store = InMemoryMemoryStore()

adapter = MCPAdapter(
    memory_store=memory_store,
)

# Memory items accessible as MCP resources:
# - memory://conversation/{id}
# - memory://session/{id}
```

### Example 3: Expose Blueprints as Prompts

```python
from cemaf.mcp import MCPAdapter
from cemaf.blueprint import Blueprint

blueprints = [
    Blueprint(
        id="content_gen",
        name="Content Generation",
        scene_goal=SceneGoal(objective="Generate blog post"),
    ),
]

adapter = MCPAdapter(blueprints=blueprints)

# Blueprints accessible as MCP prompts:
# - blueprint://content_gen
```

## Observability Integration

MCP adapter integrates with CEMAF's observability stack:

```python
from cemaf.observability import RunLogger
from cemaf.events import EventBus

run_logger = RunLogger()
event_bus = EventBus()

adapter = MCPAdapter(
    tools=tools,
    run_logger=run_logger,
    event_bus=event_bus,
)

# All MCP operations are logged:
# - Tool calls recorded in RunLogger
# - Events emitted to EventBus
# - Correlation IDs for tracing
```

## Error Handling

MCP adapter handles errors gracefully:

```python
# Invalid method
try:
    result = await adapter.handle_request(
        MCPRequest(method="unknown/method", ...)
    )
except MCPError as e:
    if e.code == MCPErrorCode.METHOD_NOT_FOUND:
        # Handle method not found
        pass

# Tool execution errors
try:
    result = await ToolBridge.call(tool, arguments)
except Exception as e:
    # Convert to MCP error
    mcp_error = MCPError(
        code=MCPErrorCode.INTERNAL_ERROR,
        message=str(e),
    )
```

## Testing

Use mock transports for testing:

```python
from cemaf.mcp import MockTransport, InMemoryTransport

# Mock transport for unit tests
transport = MockTransport()

# In-memory transport for integration tests
transport = InMemoryTransport()
await adapter.serve(transport)
```

## Protocol Methods

### Tools

- `tools/list`: List available tools
- `tools/call`: Execute a tool

### Resources

- `resources/list`: List available resources
- `resources/read`: Get resource contents

### Prompts

- `prompts/list`: List available prompts
- `prompts/get`: Get prompt template

## Best Practices

1. **Use correlation IDs**: Pass correlation IDs through for tracing
2. **Handle errors gracefully**: Convert exceptions to MCP errors
3. **Log operations**: Use RunLogger for all MCP operations
4. **Emit events**: Use EventBus for MCP events
5. **Validate inputs**: Validate MCP request parameters
6. **Use appropriate transports**: Choose transport based on deployment

## Related Modules

- **Tools**: CEMAF tools exposed as MCP tools
- **Memory**: Memory stores exposed as MCP resources
- **Blueprint**: Blueprints exposed as MCP prompts
- **Observability**: RunLogger and EventBus integration
- **Events**: MCP operations emit events
