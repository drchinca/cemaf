"""
LLM protocols - Abstract interfaces for language model clients.

Supports:
- Text completion (sync and streaming)
- Tool/function calling
- Multiple message roles
- Token counting
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from cemaf.core.types import JSON, TokenCount

# Type alias for message content - supports text and structured content (multimodal)
MessageContent = str | list[dict[str, Any]]


class MessageRole(str, Enum):
    """Role of a message in a conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True)
class Message:
    """
    A single message in a conversation.

    Supports text content and tool calls/results.
    """

    role: MessageRole
    content: MessageContent
    name: str | None = None  # For tool messages
    tool_call_id: str | None = None  # For tool results
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)
    metadata: JSON = field(default_factory=dict)

    @classmethod
    def system(cls, content: MessageContent, *, metadata: JSON | None = None) -> Message:
        """Create a system message."""
        return cls(role=MessageRole.SYSTEM, content=content, metadata=metadata or {})

    @classmethod
    def user(cls, content: MessageContent, *, metadata: JSON | None = None) -> Message:
        """Create a user message."""
        return cls(role=MessageRole.USER, content=content, metadata=metadata or {})

    @classmethod
    def assistant(
        cls,
        content: MessageContent,
        tool_calls: tuple[ToolCall, ...] = (),
        *,
        metadata: JSON | None = None,
    ) -> Message:
        """Create an assistant message."""
        return cls(
            role=MessageRole.ASSISTANT,
            content=content,
            tool_calls=tool_calls,
            metadata=metadata or {},
        )

    @classmethod
    def tool_result(
        cls,
        tool_call_id: str,
        content: MessageContent,
        name: str | None = None,
        *,
        metadata: JSON | None = None,
    ) -> Message:
        """Create a tool result message."""
        return cls(
            role=MessageRole.TOOL,
            content=content,
            name=name,
            tool_call_id=tool_call_id,
            metadata=metadata or {},
        )

    def to_dict(self) -> JSON:
        """Convert to API-compatible dict."""
        d: JSON = {"role": self.role.value, "content": self.content}
        if self.name:
            d["name"] = self.name
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            d["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        if self.metadata:
            d["metadata"] = self.metadata
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        """Create a Message from a serialized dict."""
        role = MessageRole(data.get("role", "user"))
        tool_calls_data = data.get("tool_calls", []) or []
        tool_calls = tuple(ToolCall.from_dict(tc) for tc in tool_calls_data)
        return cls(
            role=role,
            content=data.get("content", ""),
            name=data.get("name"),
            tool_call_id=data.get("tool_call_id"),
            tool_calls=tool_calls,
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class ToolCall:
    """
    A tool call requested by the LLM.

    The LLM wants to call a tool with these arguments.
    """

    id: str
    name: str
    arguments: JSON = field(default_factory=dict)

    def to_dict(self) -> JSON:
        """Convert to API-compatible dict."""
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": self.arguments,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolCall:
        """Create a ToolCall from a serialized dict."""
        function = data.get("function", {}) if isinstance(data.get("function"), dict) else {}
        return cls(
            id=data.get("id", ""),
            name=function.get("name") or data.get("name", ""),
            arguments=function.get("arguments", data.get("arguments", {})),
        )


@dataclass(frozen=True)
class ToolDefinition:
    """
    Definition of a tool for LLM function calling.

    Describes what a tool does and its parameters.
    """

    name: str
    description: str
    parameters: JSON = field(default_factory=lambda: {"type": "object", "properties": {}})
    required: tuple[str, ...] = field(default_factory=tuple)

    def to_openai_format(self) -> JSON:
        """Convert to OpenAI tool format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    **self.parameters,
                    "required": list(self.required),
                },
            },
        }

    def to_anthropic_format(self) -> JSON:
        """Convert to Anthropic tool format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                **self.parameters,
                "required": list(self.required),
            },
        }


class LLMConfig(BaseModel):
    """Configuration for LLM client."""

    model_config = {"frozen": True}

    model: str = "gpt-4"
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 1.0
    stop_sequences: tuple[str, ...] = Field(default_factory=tuple)
    timeout_seconds: float = 60.0


@dataclass(frozen=True)
class CompletionResult:
    """
    Result of a completion request.

    Contains the response and metadata.
    """

    success: bool
    message: Message | None = None
    error: str | None = None

    # Token usage
    prompt_tokens: TokenCount = TokenCount(0)
    completion_tokens: TokenCount = TokenCount(0)
    total_tokens: TokenCount = TokenCount(0)

    # Timing
    latency_ms: float = 0.0

    # Model info
    model: str = ""
    finish_reason: str = ""

    metadata: JSON = field(default_factory=dict)

    @classmethod
    def ok(
        cls,
        message: Message,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        model: str = "",
        finish_reason: str = "stop",
        latency_ms: float = 0.0,
    ) -> CompletionResult:
        """Create a successful result."""
        return cls(
            success=True,
            message=message,
            prompt_tokens=TokenCount(prompt_tokens),
            completion_tokens=TokenCount(completion_tokens),
            total_tokens=TokenCount(prompt_tokens + completion_tokens),
            model=model,
            finish_reason=finish_reason,
            latency_ms=latency_ms,
        )

    @classmethod
    def fail(cls, error: str) -> CompletionResult:
        """Create a failed result."""
        return cls(success=False, error=error)

    @property
    def content(self) -> MessageContent:
        """Get the message content, or empty string if no message."""
        return self.message.content if self.message else ""

    @property
    def tool_calls(self) -> tuple[ToolCall, ...]:
        """Get tool calls from the message."""
        return self.message.tool_calls if self.message else ()


@dataclass(frozen=True)
class StreamChunk:
    """
    A single chunk from a streaming response.

    Used for incremental output display.
    """

    content: str = ""
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)
    finish_reason: str | None = None
    is_final: bool = False

    # Running totals (updated each chunk)
    accumulated_content: str = ""
    prompt_tokens: TokenCount = TokenCount(0)
    completion_tokens: TokenCount = TokenCount(0)


@runtime_checkable
class LLMClient(Protocol):
    """
    Protocol for LLM clients.

    Implement this for different LLM providers:
    - OpenAI
    - Anthropic
    - Local models (Ollama, vLLM)
    - Azure OpenAI
    - etc.
    """

    @property
    def config(self) -> LLMConfig:
        """Get client configuration."""
        ...

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> CompletionResult:
        """
        Generate a completion.

        Args:
            messages: Conversation history
            tools: Available tools for function calling
            config_override: Override default config for this request

        Returns:
            CompletionResult with response or error
        """
        ...

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """
        Generate a streaming completion.

        Args:
            messages: Conversation history
            tools: Available tools for function calling
            config_override: Override default config for this request

        Yields:
            StreamChunk with incremental content
        """
        ...

    def count_tokens(self, text: str) -> TokenCount:
        """
        Count tokens in text.

        Used for context budget management.
        """
        ...

    def count_messages_tokens(self, messages: list[Message]) -> TokenCount:
        """
        Count tokens in a list of messages.

        Includes message overhead (role tokens, etc).
        """
        ...
