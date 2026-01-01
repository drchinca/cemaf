"""
MCP (Model Context Protocol) protocols and types.

JSON-RPC 2.0 message types and transport abstraction for MCP communication.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from cemaf.core.types import JSON


# JSON-RPC 2.0 Error Codes
class MCPErrorCode:
    """Standard JSON-RPC 2.0 error codes."""

    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    SERVER_ERROR = -32000  # -32000 to -32099 reserved for server errors


@dataclass(frozen=True)
class MCPError:
    """
    JSON-RPC 2.0 error object.

    Represents an error that occurred during request processing.
    Immutable for thread safety.
    """

    code: int
    message: str
    data: JSON | None = None

    @classmethod
    def parse_error(cls, message: str = "Parse error") -> MCPError:
        """Create a parse error (-32700)."""
        return cls(MCPErrorCode.PARSE_ERROR, message)

    @classmethod
    def invalid_request(cls, message: str = "Invalid request") -> MCPError:
        """Create an invalid request error (-32600)."""
        return cls(MCPErrorCode.INVALID_REQUEST, message)

    @classmethod
    def method_not_found(cls, method: str) -> MCPError:
        """Create a method not found error (-32601)."""
        return cls(MCPErrorCode.METHOD_NOT_FOUND, f"Method not found: {method}")

    @classmethod
    def invalid_params(cls, message: str) -> MCPError:
        """Create an invalid params error (-32602)."""
        return cls(MCPErrorCode.INVALID_PARAMS, message)

    @classmethod
    def internal_error(cls, message: str = "Internal error") -> MCPError:
        """Create an internal error (-32603)."""
        return cls(MCPErrorCode.INTERNAL_ERROR, message)

    @classmethod
    def server_error(cls, code: int, message: str, data: JSON | None = None) -> MCPError:
        """
        Create a server error (-32000 to -32099).

        Args:
            code: Error code (must be between -32099 and -32000).
            message: Error message.
            data: Optional additional error data.

        Returns:
            MCPError instance.

        Raises:
            ValueError: If code is not in valid server error range.
        """
        if not (-32099 <= code <= -32000):
            raise ValueError(f"Server error code must be between -32099 and -32000, got {code}")
        return cls(code, message, data)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.data is not None:
            result["data"] = self.data
        return result


@dataclass(frozen=True)
class MCPRequest:
    """
    JSON-RPC 2.0 request.

    Represents a method call from client to server.
    Immutable for thread safety.
    """

    method: str
    params: JSON = field(default_factory=dict)
    id: str | int | None = None
    jsonrpc: str = "2.0"

    @property
    def is_notification(self) -> bool:
        """Whether this is a notification (no id means no response expected)."""
        return self.id is None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result: dict[str, Any] = {"jsonrpc": self.jsonrpc, "method": self.method}
        if self.params:
            result["params"] = self.params
        if self.id is not None:
            result["id"] = self.id
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MCPRequest:
        """
        Create from dictionary.

        Args:
            data: Dictionary with request fields.

        Returns:
            MCPRequest instance.
        """
        return cls(
            method=data.get("method", ""),
            params=data.get("params", {}),
            id=data.get("id"),
            jsonrpc=data.get("jsonrpc", "2.0"),
        )

    @classmethod
    def create(
        cls,
        method: str,
        params: JSON | None = None,
        id: str | int | None = None,
    ) -> MCPRequest:
        """
        Factory method to create a request.

        Args:
            method: Method name to call.
            params: Method parameters.
            id: Request identifier (omit for notifications).

        Returns:
            MCPRequest instance.
        """
        return cls(
            method=method,
            params=params or {},
            id=id,
        )

    @classmethod
    def notification(cls, method: str, params: JSON | None = None) -> MCPRequest:
        """
        Create a notification (request without id, expects no response).

        Args:
            method: Method name to call.
            params: Method parameters.

        Returns:
            MCPRequest instance with no id.
        """
        return cls(method=method, params=params or {}, id=None)


@dataclass(frozen=True)
class MCPResponse:
    """
    JSON-RPC 2.0 response.

    Represents the result of a method call.
    Contains either result or error, never both.
    Immutable for thread safety.
    """

    id: str | int | None = None
    result: JSON | None = None
    error: MCPError | None = None
    jsonrpc: str = "2.0"

    @property
    def is_success(self) -> bool:
        """Whether this response indicates success."""
        return self.error is None

    @property
    def is_error(self) -> bool:
        """Whether this response indicates an error."""
        return self.error is not None

    @classmethod
    def success(cls, id: str | int | None, result: JSON) -> MCPResponse:
        """
        Create a success response.

        Args:
            id: Request identifier this responds to.
            result: Result value.

        Returns:
            MCPResponse with result.
        """
        return cls(id=id, result=result)

    @classmethod
    def failure(cls, id: str | int | None, error: MCPError) -> MCPResponse:
        """
        Create an error response.

        Args:
            id: Request identifier this responds to.
            error: Error object.

        Returns:
            MCPResponse with error.
        """
        return cls(id=id, error=error)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result: dict[str, Any] = {"jsonrpc": self.jsonrpc, "id": self.id}
        if self.error is not None:
            result["error"] = self.error.to_dict()
        else:
            result["result"] = self.result
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MCPResponse:
        """
        Create from dictionary.

        Args:
            data: Dictionary with response fields.

        Returns:
            MCPResponse instance.
        """
        error = None
        if "error" in data:
            err_data = data["error"]
            error = MCPError(
                code=err_data.get("code", 0),
                message=err_data.get("message", ""),
                data=err_data.get("data"),
            )
        return cls(
            id=data.get("id"),
            result=data.get("result"),
            error=error,
            jsonrpc=data.get("jsonrpc", "2.0"),
        )


@runtime_checkable
class Transport(Protocol):
    """
    Abstract transport protocol for MCP communication.

    Implementations can use stdio, WebSocket, HTTP SSE, etc.
    This protocol defines the contract that all transports must follow.

    Example implementations:
        - StdioTransport: Communicates via stdin/stdout
        - WebSocketTransport: Communicates via WebSocket connection
        - SSETransport: Server-Sent Events over HTTP
    """

    @property
    def is_connected(self) -> bool:
        """
        Whether transport is currently connected.

        Returns:
            True if connected and ready for communication.
        """
        ...

    async def connect(self) -> None:
        """
        Establish connection.

        This should be called before send/receive operations.

        Raises:
            ConnectionError: If connection cannot be established.
        """
        ...

    async def disconnect(self) -> None:
        """
        Close connection.

        After disconnection, is_connected should return False.
        Safe to call multiple times.
        """
        ...

    async def send(self, response: MCPResponse) -> None:
        """
        Send response message.

        Args:
            response: Response to send to the client.

        Raises:
            ConnectionError: If not connected.
            IOError: If send fails.
        """
        ...

    async def receive(self) -> MCPRequest:
        """
        Receive request message.

        Blocks until a request is received.

        Returns:
            MCPRequest received from client.

        Raises:
            ConnectionError: If not connected or connection lost.
            IOError: If receive fails.
            MCPError: If received data is malformed.
        """
        ...


@runtime_checkable
class MessageHandler(Protocol):
    """
    Protocol for handling MCP requests.

    Implementations process requests and return responses.
    """

    async def handle(self, request: MCPRequest) -> MCPResponse:
        """
        Handle an MCP request.

        Args:
            request: The request to process.

        Returns:
            MCPResponse with result or error.
        """
        ...


@runtime_checkable
class MethodRegistry(Protocol):
    """
    Protocol for registering and looking up MCP methods.

    Implementations manage the mapping from method names to handlers.
    """

    def register(
        self,
        method: str,
        handler: MessageHandler,
    ) -> None:
        """
        Register a handler for a method.

        Args:
            method: Method name.
            handler: Handler to invoke for this method.
        """
        ...

    def get_handler(self, method: str) -> MessageHandler | None:
        """
        Get handler for a method.

        Args:
            method: Method name to look up.

        Returns:
            Handler if registered, None otherwise.
        """
        ...

    def list_methods(self) -> list[str]:
        """
        List all registered methods.

        Returns:
            List of method names.
        """
        ...
