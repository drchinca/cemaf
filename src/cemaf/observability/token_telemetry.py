"""
Token Telemetry - Track token usage for cost analysis and optimization.

Provides utilities for tracking token consumption (in/out/saved) across
agent executions, enabling cost analysis and context density management.
"""

import logging

from cemaf.core.types import JSON
from cemaf.llm.protocols import CompletionResult
from cemaf.llm.tiktoken_estimator import get_estimator

logger = logging.getLogger(__name__)


def extract_token_metadata(
    llm_result: CompletionResult | None = None,
    input_text: str | None = None,
    output_text: str | None = None,
    model: str = "gpt-4",
    agent_name: str | None = None,
) -> JSON:
    """
    Extract token telemetry metadata from LLM results or text.

    Args:
        llm_result: CompletionResult from LLM call (preferred)
        input_text: Input text for token counting (fallback)
        output_text: Output text for token counting (fallback)
        model: Model name for accurate token counting
        agent_name: Agent name for context (e.g., "Summarizer" for tokens_saved)

    Returns:
        Dictionary with token telemetry:
        - tokens_in: Input tokens
        - tokens_out: Output tokens
        - tokens_total: Total tokens
        - tokens_saved: Tokens saved (for Summarizer)
        - cost_estimate: Estimated cost in USD (if pricing available)
    """
    metadata: JSON = {}

    # Prefer LLM result if available (most accurate)
    if llm_result:
        tokens_in = int(llm_result.prompt_tokens) if llm_result.prompt_tokens else 0
        tokens_out = int(llm_result.completion_tokens) if llm_result.completion_tokens else 0
        tokens_total = int(llm_result.total_tokens) if llm_result.total_tokens else (tokens_in + tokens_out)
        model_name = llm_result.model or model
    else:
        # Fallback: estimate from text
        estimator = get_estimator(model)
        tokens_in = estimator.estimate(input_text or "")
        tokens_out = estimator.estimate(output_text or "")
        tokens_total = tokens_in + tokens_out
        model_name = model

    metadata["tokens_in"] = tokens_in
    metadata["tokens_out"] = tokens_out
    metadata["tokens_total"] = tokens_total

    # Calculate tokens saved for Summarizer (context reduction)
    if agent_name == "Summarizer" and tokens_in > 0:
        tokens_saved = max(0, tokens_in - tokens_out)
        metadata["tokens_saved"] = tokens_saved
        metadata["compression_ratio"] = round(tokens_out / tokens_in, 3) if tokens_in > 0 else 0.0

    # Estimate cost if pricing available
    try:
        from cemaf.observability.cost_tracking import ModelPricingRegistry

        cost = ModelPricingRegistry.calculate_cost(
            model_id=model_name,
            prompt_tokens=tokens_in,
            completion_tokens=tokens_out,
        )
        if cost is not None:
            metadata["cost_estimate_usd"] = round(cost, 6)
    except Exception as e:
        logger.debug(f"Could not calculate cost estimate: {e}")

    return metadata


def count_tokens(text: str, model: str = "gpt-4") -> int:
    """
    Count tokens in text using tiktoken estimator.

    Convenience function for token counting.

    Args:
        text: Text to count tokens for
        model: Model name for encoding selection

    Returns:
        Estimated token count
    """
    estimator = get_estimator(model)
    return estimator.estimate(text)


def merge_token_metadata(metadata_list: list[JSON]) -> JSON:
    """
    Merge token metadata from multiple sources.

    Useful for aggregating token usage across multiple LLM calls in a single node.

    Args:
        metadata_list: List of token metadata dictionaries

    Returns:
        Merged metadata with totals
    """
    total_in = sum(m.get("tokens_in", 0) for m in metadata_list)
    total_out = sum(m.get("tokens_out", 0) for m in metadata_list)
    total_saved = sum(m.get("tokens_saved", 0) for m in metadata_list)
    total_cost = sum(m.get("cost_estimate_usd", 0.0) for m in metadata_list)

    return {
        "tokens_in": total_in,
        "tokens_out": total_out,
        "tokens_total": total_in + total_out,
        "tokens_saved": total_saved,
        "cost_estimate_usd": round(total_cost, 6),
        "llm_calls": len(metadata_list),
    }
