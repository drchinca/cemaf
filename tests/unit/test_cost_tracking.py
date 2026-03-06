"""Tests for observability cost tracking."""

import pytest

from cemaf.observability.cost_tracking import ModelPricing, ModelPricingRegistry


class TestModelPricing:
    def test_basic_cost_calculation(self):
        pricing = ModelPricing(
            model_id="test-model",
            prompt_price_per_million=10.0,
            completion_price_per_million=30.0,
        )
        cost = pricing.calculate_cost(prompt_tokens=1000, completion_tokens=500)
        expected = (1000 / 1_000_000) * 10.0 + (500 / 1_000_000) * 30.0
        assert cost == pytest.approx(expected)

    def test_zero_tokens(self):
        pricing = ModelPricing(
            model_id="test", prompt_price_per_million=10.0, completion_price_per_million=30.0
        )
        assert pricing.calculate_cost(prompt_tokens=0, completion_tokens=0) == 0.0

    def test_cache_cost_calculation(self):
        pricing = ModelPricing(
            model_id="test",
            prompt_price_per_million=10.0,
            completion_price_per_million=30.0,
            cache_read_price_per_million=1.0,
            cache_write_price_per_million=5.0,
        )
        cost = pricing.calculate_cost(
            prompt_tokens=1000,
            completion_tokens=500,
            cache_read_tokens=2000,
            cache_write_tokens=1000,
        )
        expected = (
            (1000 / 1_000_000) * 10.0
            + (500 / 1_000_000) * 30.0
            + (2000 / 1_000_000) * 1.0
            + (1000 / 1_000_000) * 5.0
        )
        assert cost == pytest.approx(expected)

    def test_large_token_counts(self):
        pricing = ModelPricing(
            model_id="test", prompt_price_per_million=15.0, completion_price_per_million=75.0
        )
        cost = pricing.calculate_cost(prompt_tokens=1_000_000, completion_tokens=500_000)
        assert cost == pytest.approx(15.0 + 37.5)


class TestModelPricingRegistry:
    def test_get_known_model(self):
        pricing = ModelPricingRegistry.get_pricing(model_id="gpt-4o")
        assert pricing is not None
        assert pricing.model_id == "gpt-4o"

    def test_get_unknown_model(self):
        pricing = ModelPricingRegistry.get_pricing(model_id="nonexistent-model-xyz")
        assert pricing is None

    def test_prefix_match(self):
        pricing = ModelPricingRegistry.get_pricing(model_id="claude-opus-4-5-20251101")
        assert pricing is not None
        assert pricing.model_id == "claude-opus-4-5"

    def test_calculate_cost_known_model(self):
        cost = ModelPricingRegistry.calculate_cost(
            model_id="gpt-4o",
            prompt_tokens=1000,
            completion_tokens=500,
        )
        assert cost is not None
        assert cost > 0

    def test_calculate_cost_unknown_model(self):
        cost = ModelPricingRegistry.calculate_cost(
            model_id="nonexistent",
            prompt_tokens=1000,
            completion_tokens=500,
        )
        assert cost is None

    def test_register_custom_pricing(self):
        custom = ModelPricing(
            model_id="my-custom-model",
            prompt_price_per_million=5.0,
            completion_price_per_million=15.0,
        )
        ModelPricingRegistry.register_custom_pricing(pricing=custom)

        retrieved = ModelPricingRegistry.get_pricing(model_id="my-custom-model")
        assert retrieved is not None
        assert retrieved.prompt_price_per_million == 5.0

        # Cleanup
        del ModelPricingRegistry.PRICING["my-custom-model"]

    def test_get_all_models(self):
        models = ModelPricingRegistry.get_all_models()
        assert len(models) > 0
        assert "gpt-4o" in models
        assert "claude-opus-4-5" in models

    def test_claude_pricing_present(self):
        for model in ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"]:
            pricing = ModelPricingRegistry.get_pricing(model_id=model)
            assert pricing is not None, f"Missing pricing for {model}"
