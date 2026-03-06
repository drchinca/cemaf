"""Contract tests for connecting dead flags: compressible, allocations, tokenizer."""

from cemaf.context.algorithm import GreedySelectionAlgorithm
from cemaf.context.budget import TokenBudget
from cemaf.context.source import ContextSource
from cemaf.core.types import TokenCount


class TestCompressibleFlag:
    """Contract: selection algorithms must track compressible in exclusion details."""

    def test_excluded_compressible_sources_flagged(self) -> None:
        """Excluded sources must carry compressible=True/False in exclusion details."""
        algo = GreedySelectionAlgorithm()
        budget = TokenBudget(max_tokens=100, reserved_for_output=0)

        sources = [
            ContextSource(content="important", token_count=TokenCount(60), priority=10, compressible=False),
            ContextSource(content="big doc", token_count=TokenCount(80), priority=5, compressible=True),
        ]

        result = algo.select_sources(sources=sources, budget=budget)

        assert len(result.selected_sources) == 1
        excluded = result.metadata.get("excluded_details", [])
        assert len(excluded) == 1
        assert excluded[0].get("compressible") is True

    def test_non_compressible_excluded_flagged(self) -> None:
        """Non-compressible excluded sources must be flagged as compressible=False."""
        algo = GreedySelectionAlgorithm()
        budget = TokenBudget(max_tokens=50, reserved_for_output=0)

        sources = [
            ContextSource(content="a", token_count=TokenCount(30), priority=10, compressible=True),
            ContextSource(content="b", token_count=TokenCount(30), priority=5, compressible=False),
        ]

        result = algo.select_sources(sources=sources, budget=budget)

        excluded = result.metadata.get("excluded_details", [])
        assert len(excluded) == 1
        assert excluded[0].get("compressible") is False


class TestSmartTokenEstimator:
    """Contract: create_token_estimator() should prefer tiktoken when available."""

    def test_smart_estimator_returns_estimator(self) -> None:
        """create_token_estimator() must return a valid TokenEstimator."""
        from cemaf.context.compiler import TokenEstimator
        from cemaf.context.factories import create_token_estimator

        estimator = create_token_estimator()
        assert isinstance(estimator, TokenEstimator)

    def test_smart_estimator_accepts_model(self) -> None:
        """create_token_estimator(model=...) should use model-specific tokenizer if available."""
        from cemaf.context.factories import create_token_estimator

        estimator = create_token_estimator(model="gpt-4")
        result = estimator.estimate(text="hello world")
        assert result > 0

    def test_smart_estimator_fallback(self) -> None:
        """If model is unknown, should still return a working estimator."""
        from cemaf.context.factories import create_token_estimator

        estimator = create_token_estimator(model="totally-unknown-model-xyz")
        result = estimator.estimate(text="hello world")
        assert result > 0
