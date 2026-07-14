"""Compatibility wrapper for the native OpenAI Responses adapter.

New code should import `OpenAIResponsesLLMClient` from
`cemaf.llm.openai_responses` or use `create_llm_client("openai")`.
This module keeps the historical `cemaf.llm.openai.OpenAILLMClient` import path
without maintaining a second OpenAI implementation.
"""

from __future__ import annotations

from cemaf.llm.openai_responses import OpenAIResponsesLLMClient


class OpenAILLMClient(OpenAIResponsesLLMClient):
    """Backward-compatible name for `OpenAIResponsesLLMClient`."""


__all__ = ["OpenAILLMClient"]
