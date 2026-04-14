"""
LLM module — 6 providers out of the box.

Quickstart:
    from cemaf.llm import create_llm_client

    # Local (Ollama — Qwen, Gemma, Llama)
    client = create_llm_client("ollama", model="qwen3.5")

    # Cloud
    client = create_llm_client("openai", model="gpt-4o")
    client = create_llm_client("anthropic", model="claude-sonnet-4-20250514")
    client = create_llm_client("gemini", model="gemini-2.5-flash")
    client = create_llm_client("groq", model="llama-3.3-70b-versatile")
    client = create_llm_client("together", model="meta-llama/Llama-3.3-70B-Instruct-Turbo")
"""

from cemaf.llm.anthropic import AnthropicLLMClient
from cemaf.llm.factories import (
    create_llm_client,
    create_llm_client_from_config,
    create_mock_llm_client,
)
from cemaf.llm.gemini import GeminiClient
from cemaf.llm.instrumented import InstrumentedLLMClient
from cemaf.llm.mock import MockLLMClient
from cemaf.llm.openai_compat import OpenAICompatClient
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
    # Adapters
    "OpenAICompatClient",  # OpenAI, Ollama, vLLM, Groq, Together, LMStudio
    "AnthropicLLMClient",  # Anthropic Claude
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
