"""
LLM cost tracking and calculation utilities.

Provides model pricing registry and cost calculation for tokens.
Supports all major LLM providers with up-to-date pricing information.

Example:
    from cemaf.observability.cost_tracking import ModelPricingRegistry

    # Calculate cost
    cost = ModelPricingRegistry.calculate_cost("claude-opus-4-5", 1000, 500)
    print(f"Cost: ${cost:.4f}")

    # Register custom pricing
    from cemaf.observability.cost_tracking import ModelPricing
    ModelPricingRegistry.register_custom_pricing(
        ModelPricing("custom-model", 2.0, 10.0)
    )
"""

from dataclasses import dataclass
from typing import ClassVar


@dataclass
class ModelPricing:
    """Pricing information for an LLM model."""

    model_id: str
    """Model identifier"""

    prompt_price_per_million: float
    """USD cost per 1 million prompt tokens"""

    completion_price_per_million: float
    """USD cost per 1 million completion tokens"""

    def calculate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """
        Calculate total cost in USD for given tokens.

        Args:
            prompt_tokens: Number of prompt tokens
            completion_tokens: Number of completion tokens

        Returns:
            Total cost in USD (not rounded)
        """
        prompt_cost = (prompt_tokens / 1_000_000) * self.prompt_price_per_million
        completion_cost = (completion_tokens / 1_000_000) * self.completion_price_per_million
        return prompt_cost + completion_cost


class ModelPricingRegistry:
    """
    Registry of model pricing information.

    Provides lookup and registration of LLM model pricing.
    Pricing data as of January 2026 and should be updated periodically.
    """

    # Pricing information for known models (as of January 2026)
    PRICING: ClassVar[dict[str, ModelPricing]] = {
        # Anthropic Claude
        "claude-opus-4-5": ModelPricing("claude-opus-4-5", 15.0, 75.0),
        "claude-sonnet-4-5": ModelPricing("claude-sonnet-4-5", 3.0, 15.0),
        "claude-haiku-4-5": ModelPricing("claude-haiku-4-5", 0.8, 4.0),
        # OpenAI GPT
        "gpt-4-turbo": ModelPricing("gpt-4-turbo", 10.0, 30.0),
        "gpt-4": ModelPricing("gpt-4", 30.0, 60.0),
        "gpt-3.5-turbo": ModelPricing("gpt-3.5-turbo", 0.5, 1.5),
        # Google Gemini
        "gemini-pro": ModelPricing("gemini-pro", 0.5, 1.5),
        "gemini-1.5-pro": ModelPricing("gemini-1.5-pro", 7.0, 21.0),
        # Meta Llama (via providers)
        "llama-2-70b": ModelPricing("llama-2-70b", 1.0, 1.0),
    }

    @classmethod
    def get_pricing(cls, model_id: str) -> ModelPricing | None:
        """
        Get pricing for a model.

        Supports both exact matches and prefix matches for versioned model IDs.
        For example, "claude-opus-4-5-20251101" matches "claude-opus-4-5".

        Args:
            model_id: Model identifier

        Returns:
            ModelPricing if found, None otherwise
        """
        # Try exact match first
        if model_id in cls.PRICING:
            return cls.PRICING[model_id]

        # Try prefix match (for versioned model IDs)
        for key, pricing in cls.PRICING.items():
            if model_id.startswith(key):
                return pricing

        return None

    @classmethod
    def register_custom_pricing(cls, pricing: ModelPricing) -> None:
        """
        Register custom pricing for a model.

        Useful for custom models or when you have different pricing
        from your LLM provider.

        Args:
            pricing: ModelPricing instance with model ID and pricing

        Example:
            ModelPricingRegistry.register_custom_pricing(
                ModelPricing("my-custom-model", 5.0, 15.0)
            )
        """
        cls.PRICING[pricing.model_id] = pricing

    @classmethod
    def calculate_cost(
        cls,
        model_id: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> float | None:
        """
        Calculate cost for a model.

        Args:
            model_id: Model identifier
            prompt_tokens: Number of prompt tokens
            completion_tokens: Number of completion tokens

        Returns:
            Cost in USD if pricing found, None if model not in registry
        """
        pricing = cls.get_pricing(model_id)
        if pricing:
            return pricing.calculate_cost(prompt_tokens, completion_tokens)
        return None

    @classmethod
    def get_all_models(cls) -> list[str]:
        """
        Get list of all registered models.

        Returns:
            List of model IDs
        """
        return list(cls.PRICING.keys())
