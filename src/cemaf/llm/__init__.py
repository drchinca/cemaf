"""
LLM module - free-first factories plus explicit provider adapters.

Quickstart:
    from cemaf.llm import create_llm_client, LLMBackend

    # Local/free default path (Ollama - Gemma by default)
    client = create_llm_client(LLMBackend.OLLAMA)

    # Any cloud or paid provider is explicit opt-in:
    # client = create_llm_client(LLMBackend.OPENAI, api_key="...", model="...")
"""

from cemaf.core.types import LLMBackend
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

__all__ = [
    # Backend selection
    "LLMBackend",
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
