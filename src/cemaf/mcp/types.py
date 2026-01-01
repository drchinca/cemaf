"""
MCP (Model Context Protocol) type definitions.

These types are compatible with the MCP specification and provide
frozen dataclasses for immutability.
"""

from dataclasses import dataclass, field

from cemaf.core.types import JSON


@dataclass(frozen=True)
class MCPToolDefinition:
    """
    MCP tool definition.

    Describes a callable tool with JSON Schema for parameters.
    """

    name: str
    description: str
    inputSchema: JSON = field(default_factory=dict)  # JSON Schema

    def to_dict(self) -> dict:
        """Convert to MCP-compatible dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.inputSchema,
        }


@dataclass(frozen=True)
class MCPPromptArgument:
    """Argument for an MCP prompt."""

    name: str
    description: str = ""
    required: bool = False

    def to_dict(self) -> dict:
        """Convert to MCP-compatible dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "required": self.required,
        }


@dataclass(frozen=True)
class MCPPrompt:
    """
    MCP prompt definition.

    Describes a reusable prompt template.
    """

    name: str
    description: str = ""
    arguments: tuple[MCPPromptArgument, ...] = ()

    def to_dict(self) -> dict:
        """Convert to MCP-compatible dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "arguments": [a.to_dict() for a in self.arguments],
        }


@dataclass(frozen=True)
class MCPResource:
    """
    MCP resource definition.

    Describes a readable resource (file, memory item, etc).
    """

    uri: str
    name: str
    description: str = ""
    mimeType: str = "application/json"

    def to_dict(self) -> dict:
        """Convert to MCP-compatible dictionary."""
        return {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
            "mimeType": self.mimeType,
        }


@dataclass(frozen=True)
class MCPResourceContents:
    """Contents of a resource."""

    uri: str
    mimeType: str = "application/json"
    text: str | None = None
    blob: str | None = None  # Base64 encoded

    def to_dict(self) -> dict:
        """Convert to MCP-compatible dictionary."""
        result: dict = {"uri": self.uri, "mimeType": self.mimeType}
        if self.text is not None:
            result["text"] = self.text
        if self.blob is not None:
            result["blob"] = self.blob
        return result


@dataclass(frozen=True)
class MCPToolResult:
    """Result from calling an MCP tool."""

    content: tuple[dict, ...]  # Tuple of content blocks (immutable)
    isError: bool = False

    @classmethod
    def text(cls, text: str, is_error: bool = False) -> MCPToolResult:
        """Create a text result."""
        return cls(content=({"type": "text", "text": text},), isError=is_error)

    @classmethod
    def error(cls, message: str) -> MCPToolResult:
        """Create an error result."""
        return cls(content=({"type": "text", "text": message},), isError=True)

    @classmethod
    def from_content_list(cls, content: list[dict], is_error: bool = False) -> MCPToolResult:
        """Create a result from a list of content blocks."""
        return cls(content=tuple(content), isError=is_error)

    def to_dict(self) -> dict:
        """Convert to MCP-compatible dictionary."""
        return {"content": list(self.content), "isError": self.isError}
