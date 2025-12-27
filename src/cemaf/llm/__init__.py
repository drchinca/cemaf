"""
LLM module - Language model client abstraction.

Provides:
- LLMClient protocol for pluggable LLM backends
- Message types for conversations
- Completion/streaming results
- Adapters for OpenAI, Anthropic, etc.
"""

from cemaf.llm.protocols import (
    LLMClient,
    LLMConfig,
    Message,
    MessageRole,
    CompletionResult,
    StreamChunk,
    ToolCall,
    ToolDefinition,
)
from cemaf.llm.mock import MockLLMClient

__all__ = [
    # Protocols
    "LLMClient",
    "LLMConfig",
    # Message types
    "Message",
    "MessageRole",
    # Results
    "CompletionResult",
    "StreamChunk",
    # Tool calling
    "ToolCall",
    "ToolDefinition",
    # Mock
    "MockLLMClient",
]

