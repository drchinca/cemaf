"""Ollama helpers — local LLM tiers for dev experience with zero API cost.

Ollama speaks the OpenAI chat-completions API, so any model it serves can be
consumed through `OpenAICompatClient`. This module adds two conveniences:

1. `create_ollama_client(...)` — single-model client with local-friendly defaults
   (longer timeout to absorb cold-load on first call, configurable `num_ctx`).
2. `create_tiered_ollama_router(...)` — ModelRouter that routes simple prompts
   to a fast small model (e.g. `gemma3:4b`) and complex or tool-using prompts
   to a larger one (e.g. `gemma3:12b`). Lets multi-agent DAGs pay only the
   minimum inference cost per node.

Why this is cheap: Ollama runs locally, so there is no per-token cost; the only
tradeoff is wall-clock time on the small vs. large model. `CharBasedEstimator`
is deliberately binary and simple — the default complexity estimator normalises
to 50 messages / 100k chars and effectively never escalates for single-turn
local use.

Usage:
    from cemaf.llm.ollama import create_tiered_ollama_router

    client = create_tiered_ollama_router()   # 4b for simple, 12b for complex
    # pass into RuntimeServices like any other LLMClient
"""

from __future__ import annotations

from dataclasses import dataclass

from cemaf.core.types import LLMProvider
from cemaf.llm.model_router import ModelRoute, ModelRouter
from cemaf.llm.openai_compat import OpenAICompatClient
from cemaf.llm.protocols import LLMClient, Message, ToolDefinition

DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_SMALL_MODEL = "gemma3:4b"
DEFAULT_LARGE_MODEL = "gemma3:12b"
DEFAULT_TIMEOUT_SECONDS = 300.0  # absorbs first-load model spin-up
DEFAULT_ESCALATION_CHARS = 500


def create_ollama_client(
    *,
    model: str = DEFAULT_SMALL_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> LLMClient:
    """Create an LLMClient backed by a single Ollama-hosted model.

    Uses a long default timeout because Ollama cold-loads the model on first
    request. Pass a shorter timeout if you pre-warm models with `ollama run`.
    """
    return OpenAICompatClient(
        base_url=base_url,
        api_key="",
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
        provider=LLMProvider.OLLAMA,
    )


@dataclass(frozen=True)
class CharBasedEstimator:
    """Binary complexity estimator for local tiered routing.

    Escalates to the large tier when any of:
      - tools are present
      - total prompt character count >= `escalation_chars`

    Simple, predictable, tuned for local Ollama workflows. Use
    `DefaultComplexityEstimator` when you care about graded cloud cost tiers.
    """

    escalation_chars: int = DEFAULT_ESCALATION_CHARS

    def estimate(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
    ) -> float:
        if tools:
            return 1.0
        total_chars = sum(len(m.content) if isinstance(m.content, str) else 0 for m in messages)
        return 1.0 if total_chars >= self.escalation_chars else 0.0


def create_tiered_ollama_router(
    *,
    small_model: str = DEFAULT_SMALL_MODEL,
    large_model: str = DEFAULT_LARGE_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    escalation_chars: int = DEFAULT_ESCALATION_CHARS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> ModelRouter:
    """Route simple prompts to `small_model`, complex ones to `large_model`.

    Both models must be pulled locally (`ollama pull gemma3:4b` etc.). Escalation
    fires when prompt character count >= `escalation_chars` OR the request uses
    tools. Below that threshold the small model handles the call; above it, the
    large model does.
    """
    small = create_ollama_client(
        model=small_model,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )
    large = create_ollama_client(
        model=large_model,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )
    return ModelRouter(
        routes=[
            ModelRoute(threshold=0.5, client=small, model_name=small_model),
            ModelRoute(threshold=1.0, client=large, model_name=large_model),
        ],
        estimator=CharBasedEstimator(escalation_chars=escalation_chars),
    )
