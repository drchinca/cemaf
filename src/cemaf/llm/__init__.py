"""
LLM module - free-first factories plus explicit provider adapters.

Quickstart:
    from cemaf.llm import create_llm_client

    # Local/free default path (Ollama - Gemma by default)
    client = create_llm_client("ollama")

    # Any cloud or paid provider is explicit opt-in:
    # client = create_llm_client("openai", api_key="...", model="...")

Exports resolve lazily (PEP 562): importing `cemaf.llm.protocols` — or any
module that only needs the LLMClient Protocol, like
`observability.token_telemetry` — must NOT drag in every provider adapter and
its HTTP stack. Consumers that never construct a client never load httpx.
"""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cemaf.llm.anthropic import AnthropicLLMClient
    from cemaf.llm.bedrock_cli import BedrockCliLLMClient
    from cemaf.llm.factories import (
        create_llm_client,
        create_llm_client_from_config,
        create_mock_llm_client,
        create_resilient_llm_client,
    )
    from cemaf.llm.gemini import GeminiClient
    from cemaf.llm.instrumented import InstrumentedLLMClient
    from cemaf.llm.mock import MockLLMClient
    from cemaf.llm.openai_compat import OpenAICompatClient
    from cemaf.llm.openai_responses import OpenAIResponsesLLMClient
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
    from cemaf.llm.resilient import QuerySource, ResilientLLMClient, create_resilient_client
    from cemaf.llm.response_utils import ParseResult, ResponseParser, StreamingJSONParser
    from cemaf.llm.tiktoken_estimator import TiktokenEstimator

#: name -> defining submodule, resolved on first attribute access.
_EXPORTS: dict[str, str] = {
    # Protocols / message types / results / tool calling
    "CompletionResult": "cemaf.llm.protocols",
    "LLMClient": "cemaf.llm.protocols",
    "LLMConfig": "cemaf.llm.protocols",
    "Message": "cemaf.llm.protocols",
    "MessageRole": "cemaf.llm.protocols",
    "StreamChunk": "cemaf.llm.protocols",
    "ToolCall": "cemaf.llm.protocols",
    "ToolDefinition": "cemaf.llm.protocols",
    # Top-level factories
    "create_llm_client": "cemaf.llm.factories",
    "create_llm_client_from_config": "cemaf.llm.factories",
    "create_mock_llm_client": "cemaf.llm.factories",
    "create_resilient_llm_client": "cemaf.llm.factories",
    # Adapters
    "OpenAIResponsesLLMClient": "cemaf.llm.openai_responses",
    "OpenAICompatClient": "cemaf.llm.openai_compat",
    "AnthropicLLMClient": "cemaf.llm.anthropic",
    "BedrockCliLLMClient": "cemaf.llm.bedrock_cli",
    "GeminiClient": "cemaf.llm.gemini",
    "MockLLMClient": "cemaf.llm.mock",
    # Wrappers
    "InstrumentedLLMClient": "cemaf.llm.instrumented",
    "QuerySource": "cemaf.llm.resilient",
    "ResilientLLMClient": "cemaf.llm.resilient",
    "create_resilient_client": "cemaf.llm.resilient",
    # Response utilities
    "ResponseParser": "cemaf.llm.response_utils",
    "ParseResult": "cemaf.llm.response_utils",
    "StreamingJSONParser": "cemaf.llm.response_utils",
    # Token estimation
    "TiktokenEstimator": "cemaf.llm.tiktoken_estimator",
}

__all__ = [  # noqa: RUF022 - grouped by concern, mirrors _EXPORTS
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
    # Top-level factory
    "create_llm_client",
    "create_llm_client_from_config",
    "create_mock_llm_client",
    "create_resilient_llm_client",
    # Adapters
    "OpenAIResponsesLLMClient",  # OpenAI Responses API
    "OpenAICompatClient",  # OpenAI-compatible Chat Completions gateways
    "AnthropicLLMClient",  # Anthropic Claude
    "BedrockCliLLMClient",  # AWS Bedrock via AWS CLI
    "GeminiClient",  # Google Gemini
    "MockLLMClient",  # Testing
    # Wrappers
    "InstrumentedLLMClient",
    "QuerySource",
    "ResilientLLMClient",
    "create_resilient_client",
    # Response utilities
    "ResponseParser",
    "ParseResult",
    "StreamingJSONParser",
    # Token estimation
    "TiktokenEstimator",
]


def __getattr__(name: str) -> Any:
    """Resolve exported names lazily; cache on the package for repeat access."""
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(target), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
