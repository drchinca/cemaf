"""
MCP Adapter - bridges CEMAF framework to Model Context Protocol.

This module provides the main MCPAdapter class that:
- Exposes CEMAF tools as MCP tools
- Exposes CEMAF memory stores as MCP resources
- Exposes CEMAF blueprints as MCP prompts
- Integrates with EventBus for observability
- Integrates with RunLogger for recording

Note: Uses PEP 563 () to defer annotation evaluation
and avoid circular imports.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from cemaf.blueprint.core import Blueprint
from cemaf.core.types import JSON
from cemaf.events.protocols import EventBus
from cemaf.mcp.bridges import PromptBridge, ResourceBridge, ToolBridge
from cemaf.mcp.protocols import (
    MCPError,
    MCPRequest,
    MCPResponse,
    Transport,
)
from cemaf.memory.protocols import MemoryStore
from cemaf.observability import get_logger
from cemaf.observability.run_logger import RunLogger
from cemaf.tools.protocols import Tool

logger = get_logger("mcp.adapter")

# Type alias for method handlers
MethodHandler = Callable[[JSON], Awaitable[JSON]]


class MCPAdapter:
    """
    Main MCP adapter that bridges CEMAF to Model Context Protocol.

    Capabilities:
    - tools/list, tools/call: Execute CEMAF tools
    - resources/list, resources/read: Access CEMAF memory/retrieval
    - prompts/list, prompts/get: Use CEMAF blueprints as prompts

    Example:
        adapter = MCPAdapter(transport=StdioTransport())
        adapter.register_tool(my_tool)
        adapter.register_blueprint(my_blueprint)
        await adapter.serve()
    """

    # Protocol version
    PROTOCOL_VERSION = "2024-11-05"
    SERVER_NAME = "cemaf-mcp"
    SERVER_VERSION = "1.0.0"

    def __init__(
        self,
        transport: Transport,
        event_bus: EventBus | None = None,
        run_logger: RunLogger | None = None,
    ) -> None:
        """
        Initialize the MCP adapter.

        Args:
            transport: Transport layer for communication.
            event_bus: Optional event bus for emitting events.
            run_logger: Optional run logger for recording tool calls.
        """
        self._transport = transport
        self._event_bus = event_bus
        self._run_logger = run_logger

        # Registries
        self._tools: dict[str, Tool] = {}
        self._blueprints: dict[str, Blueprint] = {}
        self._memory_store: MemoryStore | None = None
        self._pending_tasks: set[asyncio.Task[None]] = set()

        # Server state
        self._initialized = False
        self._client_info: JSON = {}

        # Method handlers
        self._methods: dict[str, MethodHandler] = {
            "initialize": self._handle_initialize,
            "initialized": self._handle_initialized,
            "ping": self._handle_ping,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
            "resources/list": self._handle_resources_list,
            "resources/read": self._handle_resources_read,
            "prompts/list": self._handle_prompts_list,
            "prompts/get": self._handle_prompts_get,
        }

    # Registration methods

    def register_tool(self, tool: Tool) -> None:
        """
        Register a CEMAF tool.

        Args:
            tool: Tool to register.
        """
        self._tools[tool.schema.name] = tool

    def register_tools(self, tools: list[Tool]) -> None:
        """
        Register multiple tools.

        Args:
            tools: List of tools to register.
        """
        for tool in tools:
            self.register_tool(tool)

    def unregister_tool(self, name: str) -> bool:
        """
        Unregister a tool by name.

        Args:
            name: Name of the tool to unregister.

        Returns:
            True if tool was removed, False if not found.
        """
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def register_blueprint(self, blueprint: Blueprint) -> None:
        """
        Register a blueprint as MCP prompt.

        Args:
            blueprint: Blueprint to register.
        """
        self._blueprints[blueprint.id] = blueprint

    def register_blueprints(self, blueprints: list[Blueprint]) -> None:
        """
        Register multiple blueprints.

        Args:
            blueprints: List of blueprints to register.
        """
        for bp in blueprints:
            self.register_blueprint(bp)

    def unregister_blueprint(self, blueprint_id: str) -> bool:
        """
        Unregister a blueprint by ID.

        Args:
            blueprint_id: ID of the blueprint to unregister.

        Returns:
            True if blueprint was removed, False if not found.
        """
        if blueprint_id in self._blueprints:
            del self._blueprints[blueprint_id]
            return True
        return False

    def set_memory_store(self, store: MemoryStore) -> None:
        """
        Set memory store for resource access.

        Args:
            store: Memory store to use.
        """
        self._memory_store = store

    # Server lifecycle

    async def serve(self) -> None:
        """
        Start serving MCP requests.

        Connects transport and enters main request/response loop.
        Runs until transport disconnects or an error occurs.
        """
        await self._transport.connect()
        self._emit_event("mcp.server.started", {})

        try:
            while self._transport.is_connected:
                try:
                    request = await self._transport.receive()
                    response = await self.handle_request(request)

                    # Only send response if not a notification
                    if request.id is not None:
                        await self._transport.send(response)

                except EOFError:
                    # Clean end of stream
                    break
                except asyncio.CancelledError:
                    # Server shutdown
                    break
                except Exception as e:
                    # Log error and send error response if possible
                    self._emit_event("mcp.server.error", {"error": str(e)})
                    if request.id is not None:
                        error_response = MCPResponse.failure(
                            request.id,
                            MCPError.internal_error(str(e)),
                        )
                        try:
                            await self._transport.send(error_response)
                        except Exception as transport_err:
                            # Log transport error and exit loop
                            logger.error(
                                "Failed to send error response, transport error: %s",
                                str(transport_err),
                                request_id=request.id,
                                exc_info=True,
                            )
                            break
        finally:
            await self._transport.disconnect()
            self._emit_event("mcp.server.stopped", {})

    async def handle_request(self, request: MCPRequest) -> MCPResponse:
        """
        Handle a single MCP request.

        Routes to appropriate method handler based on request method.

        Args:
            request: The MCP request to handle.

        Returns:
            MCPResponse with result or error.
        """
        method = request.method

        if method not in self._methods:
            return MCPResponse.failure(
                request.id,
                MCPError.method_not_found(method),
            )

        try:
            handler = self._methods[method]
            result = await handler(request.params)
            return MCPResponse.success(request.id, result)
        except ValueError as e:
            # Parameter validation errors
            return MCPResponse.failure(
                request.id,
                MCPError.invalid_params(str(e)),
            )
        except Exception as e:
            # Unexpected errors
            self._emit_event(
                "mcp.request.error",
                {
                    "method": method,
                    "error": str(e),
                },
            )
            return MCPResponse.failure(
                request.id,
                MCPError.internal_error(str(e)),
            )

    # Method handlers

    async def _handle_initialize(self, params: JSON) -> JSON:
        """
        Handle initialize request.

        Negotiates protocol version and capabilities.
        """
        # Store client info
        self._client_info = params.get("clientInfo", {})
        client_version = params.get("protocolVersion", "")

        self._emit_event(
            "mcp.client.connected",
            {
                "clientInfo": self._client_info,
                "protocolVersion": client_version,
            },
        )

        return {
            "protocolVersion": self.PROTOCOL_VERSION,
            "serverInfo": {
                "name": self.SERVER_NAME,
                "version": self.SERVER_VERSION,
            },
            "capabilities": {
                "tools": {},
                "resources": {} if self._memory_store else None,
                "prompts": {} if self._blueprints else None,
            },
        }

    async def _handle_initialized(self, params: JSON) -> JSON:
        """
        Handle initialized notification.

        Called after client confirms initialization.
        """
        self._initialized = True
        self._emit_event("mcp.server.initialized", {})
        return {}

    async def _handle_ping(self, params: JSON) -> JSON:
        """
        Handle ping request.

        Simple keepalive/health check.
        """
        return {}

    async def _handle_tools_list(self, params: JSON) -> JSON:
        """
        Handle tools/list request.

        Returns list of available tools.
        """
        params.get("cursor")
        # Pagination not implemented - return all tools
        tools = [ToolBridge.to_mcp(t).to_dict() for t in self._tools.values()]
        return {"tools": tools}

    async def _handle_tools_call(self, params: JSON) -> JSON:
        """
        Handle tools/call request.

        Executes a tool and returns the result.
        """
        name = params.get("name")
        if not name:
            raise ValueError("Missing required parameter: name")

        arguments = params.get("arguments", {})

        if name not in self._tools:
            raise ValueError(f"Tool not found: {name}")

        tool = self._tools[name]

        # Generate correlation ID for tracing
        correlation_id = ""
        if self._run_logger:
            from cemaf.core.utils import generate_id

            correlation_id = generate_id("mcp")

        result = await ToolBridge.call(
            tool,
            arguments,
            run_logger=self._run_logger,
            correlation_id=correlation_id,
        )

        self._emit_event(
            "mcp.tool.called",
            {
                "tool": name,
                "arguments": arguments,
                "success": not result.isError,
            },
        )

        return result.to_dict()

    async def _handle_resources_list(self, params: JSON) -> JSON:
        """
        Handle resources/list request.

        Returns list of available resources from memory store.
        """
        resources: list[dict[str, Any]] = []

        if self._memory_store:
            mcp_resources = await ResourceBridge.list_resources(self._memory_store)
            resources = [r.to_dict() for r in mcp_resources]

        return {"resources": resources}

    async def _handle_resources_read(self, params: JSON) -> JSON:
        """
        Handle resources/read request.

        Reads a resource by URI.
        """
        uri = params.get("uri")
        if not uri:
            raise ValueError("Missing required parameter: uri")

        if not self._memory_store:
            raise ValueError("No memory store configured")

        contents = await ResourceBridge.read_resource(self._memory_store, uri)
        if contents is None:
            raise ValueError(f"Resource not found: {uri}")

        self._emit_event("mcp.resource.read", {"uri": uri})

        return {"contents": [contents.to_dict()]}

    async def _handle_prompts_list(self, params: JSON) -> JSON:
        """
        Handle prompts/list request.

        Returns list of available prompts from blueprints.
        """
        prompts = [PromptBridge.to_mcp(bp).to_dict() for bp in self._blueprints.values()]
        return {"prompts": prompts}

    async def _handle_prompts_get(self, params: JSON) -> JSON:
        """
        Handle prompts/get request.

        Returns rendered prompt with arguments substituted.
        """
        name = params.get("name")
        if not name:
            raise ValueError("Missing required parameter: name")

        arguments = params.get("arguments", {})

        if name not in self._blueprints:
            raise ValueError(f"Prompt not found: {name}")

        blueprint = self._blueprints[name]
        text = PromptBridge.get_prompt_text(blueprint, arguments)

        self._emit_event(
            "mcp.prompt.rendered",
            {
                "name": name,
                "arguments": arguments,
            },
        )

        return {
            "messages": [
                {
                    "role": "user",
                    "content": {"type": "text", "text": text},
                }
            ],
        }

    # Event emission

    def _emit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """
        Emit event if event_bus is configured.

        Args:
            event_type: Type of event to emit.
            payload: Event payload data.
        """
        if self._event_bus is None:
            return

        from cemaf.events.protocols import Event

        event = Event.create(
            type=event_type,
            payload=payload,
            source="mcp_adapter",
        )

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._event_bus.publish(event))
            self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks.discard)
        except RuntimeError:
            pass

    # Introspection

    @property
    def is_initialized(self) -> bool:
        """Whether the server has been initialized."""
        return self._initialized

    @property
    def tool_count(self) -> int:
        """Number of registered tools."""
        return len(self._tools)

    @property
    def blueprint_count(self) -> int:
        """Number of registered blueprints."""
        return len(self._blueprints)

    @property
    def client_info(self) -> JSON:
        """Information about the connected client."""
        return dict(self._client_info)

    def list_tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    def list_blueprint_ids(self) -> list[str]:
        """Get list of registered blueprint IDs."""
        return list(self._blueprints.keys())
