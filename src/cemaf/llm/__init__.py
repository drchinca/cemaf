"""
LLM module - Language model client abstraction.

Provides:
- LLMClient protocol for pluggable LLM backends
- Message types for conversations
- Completion/streaming results
- Adapters for OpenAI, Anthropic, etc.
- Response parsing and validation utilities

Configuration:
    See cemaf.config.protocols.LLMSettings for available settings.
    Environment variables: CEMAF_LLM_*

Usage:
    # Recommended: Use factory with configuration
    from cemaf.llm import create_llm_client_from_config
    client = create_llm_client_from_config()

    # Direct instantiation
    from cemaf.llm import MockLLMClient
    client = MockLLMClient()

    # Parse LLM responses
    from cemaf.llm import ResponseParser
    result = ResponseParser.parse_json(llm_response)
"""

from cemaf.llm.factories import create_llm_client_from_config, create_mock_llm_client
from cemaf.llm.mock import MockLLMClient
from cemaf.llm.protocols import (
    CompletionResult,
    LLMClient,
    LLMConfig,
    Message,
    MessageRole,
    StreamChunk,
    ToolCall,
    ToolDefinition,
)
from cemaf.llm.response_utils import ParseResult, ResponseParser, StreamingJSONParser

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
    # Factories
    "create_llm_client_from_config",
    "create_mock_llm_client",
    # Mock
    "MockLLMClient",
    # Response utilities
    "ResponseParser",
    "ParseResult",
    "StreamingJSONParser",
]
